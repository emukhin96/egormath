#!/usr/bin/env python3
"""
Минимальный клиент S3 для копий в Selectel (deploy/VPS.md, «Копия в Selectel»).

Только стандартная библиотека: на хосте нет venv, а boto3 ради одного PUT не ставим.
Запросы подписываются AWS Signature V4, файлы идут потоком, а не целиком в памяти.
Перенесён из chemolymp (scripts/backup_s3.py, а туда — из chgkmsu), логика та же.

    python3 backup_s3.py put <файл> <ключ>      # загрузить
    python3 backup_s3.py get <ключ> <файл>      # скачать (для восстановления)
    python3 backup_s3.py list [префикс]         # ключи в бакете, по возрастанию
    python3 backup_s3.py list -l [префикс]      # «LastModified<TAB>ключ» (время ставит S3, UTC)
    python3 backup_s3.py latest <префикс>       # последний ключ, например latest daily/
    python3 backup_s3.py check-write-only       # ключ может только загружать: код 0, иначе 1
    python3 backup_s3.py selftest               # сверить подпись с примерами из документации AWS

Настройки — сначала переменная окружения, потом файл с тем же именем в каталоге
BACKUP_SECRETS_DIR (на сервере — /opt/egormath/data/offsite-keys, ключ «только запись»;
на Mac — ~/egormath/.secrets-backup-reader, ключ «чтение»):
    S3_BACKUP_ENDPOINT   https://s3.ru-6.storage.selcloud.ru
    S3_BACKUP_REGION     ru-6
    S3_BACKUP_BUCKET     egormath
    S3_BACKUP_KEY_ID, S3_BACKUP_SECRET
    S3_BACKUP_ADDRESSING vhosted (по умолчанию) или path
"""

import datetime
import hashlib
import hmac
import http.client
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SECRETS_DIR = Path(
    os.environ.get("BACKUP_SECRETS_DIR")
    or Path(__file__).resolve().parents[2] / "data" / "offsite-keys"
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
CHUNK = 1024 * 1024


def read_secret(name, default=None):
    value = os.environ.get(name)
    if value:
        return value.strip()
    path = SECRETS_DIR / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    if default is not None:
        return default
    sys.exit(f"backup_s3: не задан {name} (ни в окружении, ни в {path})")


def _quote(value):
    return urllib.parse.quote(value, safe="-_.~")


def canonical_query(params):
    return "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(params.items()))


def _hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign_v4(method, host, path, headers, payload_hash, key_id, secret, region, amz_date, query=""):
    """Возвращает значение заголовка Authorization (AWS SigV4, сервис s3).

    path — уже закодированный путь, query — канонический query string,
    headers — все подписываемые заголовки, кроме host.
    """
    date = amz_date[:8]
    signed = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    signed["host"] = host
    names = sorted(signed)
    canonical_request = "\n".join(
        [
            method,
            path,
            query,
            "".join(f"{n}:{signed[n]}\n" for n in names),
            ";".join(names),
            payload_hash,
        ]
    )
    scope = f"{date}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    key = _hmac(
        _hmac(_hmac(_hmac(("AWS4" + secret).encode("utf-8"), date), region), "s3"), "aws4_request"
    )
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def request(method, object_key="", params=None, upload=None, download=None):
    """Один запрос к бакету. upload — путь к файлу для PUT, download — куда сохранить ответ GET.

    Возвращает (HTTP-статус, тело ответа). 4xx не повторяем, 5xx и сетевые ошибки — до 3 раз.
    """
    endpoint = urllib.parse.urlsplit(read_secret("S3_BACKUP_ENDPOINT"))
    bucket = read_secret("S3_BACKUP_BUCKET")
    region = read_secret("S3_BACKUP_REGION")
    key_id = read_secret("S3_BACKUP_KEY_ID")
    secret = read_secret("S3_BACKUP_SECRET")
    addressing = read_secret("S3_BACKUP_ADDRESSING", default="vhosted")

    encoded_key = urllib.parse.quote(object_key.lstrip("/"), safe="/-_.~")
    if addressing == "path":
        host, path = endpoint.netloc, f"/{bucket}/{encoded_key}" if encoded_key else f"/{bucket}"
    else:
        host, path = f"{bucket}.{endpoint.netloc}", f"/{encoded_key}"
    query = canonical_query(params or {})
    url = f"{endpoint.scheme}://{host}{path}" + (f"?{query}" if query else "")
    payload_hash = _file_sha256(upload) if upload else EMPTY_SHA256

    last_error = None
    for attempt in range(1, 4):
        # timezone.utc, а не datetime.UTC: на Mac скрипт идёт под системным Python 3.9
        now = datetime.datetime.now(datetime.timezone.utc)  # noqa: UP017
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        headers = {"x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        headers["Authorization"] = sign_v4(
            method, host, path, headers, payload_hash, key_id, secret, region, amz_date, query
        )
        body = None
        if upload:
            # Явный Content-Length: иначе urllib шлёт файл chunked, а S3 так не принимает
            body = open(upload, "rb")
            headers["Content-Length"] = str(os.path.getsize(upload))
            headers["Content-Type"] = "application/octet-stream"
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=body, method=method, headers=headers), timeout=120
            ) as resp:
                if download:
                    part = Path(f"{download}.part")
                    with open(part, "wb") as out:
                        shutil.copyfileobj(resp, out, CHUNK)
                    part.replace(download)
                    return resp.status, b""
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:500]
            if exc.code < 500:
                return exc.code, detail
            last_error = f"HTTP {exc.code}: {detail.decode('utf-8', 'replace')}"
        # OSError — и URLError, и таймаут чтения (в Python 3.9 socket.timeout не TimeoutError),
        # HTTPException — оборванный ответ (IncompleteRead): всё это повторяем
        except (OSError, http.client.HTTPException) as exc:
            last_error = str(exc)
        finally:
            if body:
                body.close()
        time.sleep(5 * attempt)
    sys.exit(f"backup_s3: {method} {object_key or '/'} не удался после 3 попыток: {last_error}")


def _child(el, name):
    return next((c.text for c in el if c.tag.endswith("}" + name) or c.tag == name), None)


def list_keys(prefix="", with_time=False):
    """Ключи по возрастанию; with_time — пары (LastModified, ключ).

    LastModified ставит S3 при загрузке, а не клиент: по нему, а не по имени ключа, отсекаются
    объекты, загруженные после взлома сервера.
    """
    keys, token = [], None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if token:
            params["continuation-token"] = token
        status, body = request("GET", params=params)
        if status != 200:
            sys.exit(f"backup_s3: список {prefix or '/'} → HTTP {status}: {body[:500]!r}")
        root = ET.fromstring(body)
        # Теги приходят с пространством имён S3 — сравниваем по окончанию
        for el in root:
            if el.tag.endswith("}Contents") or el.tag == "Contents":
                keys.append((_child(el, "Key"), _child(el, "LastModified") or ""))
        truncated = next((el.text for el in root if el.tag.endswith("IsTruncated")), "false")
        token = next((el.text for el in root if el.tag.endswith("NextContinuationToken")), None)
        if truncated != "true" or not token:
            keys.sort()
            return [(t, k) for k, t in keys] if with_time else [k for k, _ in keys]


def check_write_only():
    """Кладёт тестовый объект и пробует его прочитать, удалить и получить список объектов.

    Настоящие копии не трогает. Запрет списка важнее остальных: защита копий от перезаписи
    (PutObject поверх) держится на случайном суффиксе в имени, а список выдал бы все имена.
    """
    probe = f"_checks/write-only-{datetime.datetime.now():%Y-%m-%d_%H%M%S}.txt"
    fd, tmp = tempfile.mkstemp(suffix=".txt")
    try:
        os.write(fd, "проверка прав ключа бэкапа\n".encode())
        os.close(fd)
        status, body = request("PUT", probe, upload=tmp)
    finally:
        os.unlink(tmp)
    if status != 200:
        sys.exit(f"✗ Загрузить тестовый объект не удалось: HTTP {status} {body[:300]!r}")
    print(f"✓ Загрузка разрешена ({probe})")
    ok = True
    checks = (
        ("чтение", lambda: request("GET", probe)),
        ("удаление", lambda: request("DELETE", probe)),
        (
            "получение списка объектов",
            lambda: request("GET", params={"list-type": "2", "prefix": ""}),
        ),
    )
    for what, call in checks:
        status, _ = call()
        if status == 403:
            print(f"✓ {what.capitalize()} запрещено (HTTP 403)")
        else:
            ok = False
            print(
                f"✗ {what.capitalize()} РАЗРЕШЕНО (HTTP {status}) — "
                "в политике бакета должно быть только s3:PutObject"
            )
    sys.exit(0 if ok else 1)


def selftest():
    """Примеры GET Object, PUT Object и List Objects из документации AWS по SigV4."""
    key_id, secret = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    host = "examplebucket.s3.amazonaws.com"
    put_hash = hashlib.sha256(b"Welcome to Amazon S3.").hexdigest()
    cases = [
        (
            "GET",
            "/test.txt",
            "",
            {
                "range": "bytes=0-9",
                "x-amz-content-sha256": EMPTY_SHA256,
                "x-amz-date": "20130524T000000Z",
            },
            EMPTY_SHA256,
            "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
        ),
        (
            "PUT",
            "/" + _quote("test$file.text"),
            "",
            {
                "date": "Fri, 24 May 2013 00:00:00 GMT",
                "x-amz-date": "20130524T000000Z",
                "x-amz-storage-class": "REDUCED_REDUNDANCY",
                "x-amz-content-sha256": put_hash,
            },
            put_hash,
            "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd",
        ),
        (
            "GET",
            "/",
            canonical_query({"max-keys": "2", "prefix": "J"}),
            {"x-amz-content-sha256": EMPTY_SHA256, "x-amz-date": "20130524T000000Z"},
            EMPTY_SHA256,
            "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7",
        ),
    ]
    for method, path, query, headers, payload_hash, expected in cases:
        auth = sign_v4(
            method,
            host,
            path,
            headers,
            payload_hash,
            key_id,
            secret,
            "us-east-1",
            "20130524T000000Z",
            query,
        )
        got = auth.rsplit("Signature=", 1)[1]
        if got != expected:
            sys.exit(
                f"backup_s3 selftest: {method} {path}?{query} — подпись {got}, ожидалась {expected}"
            )
    print("backup_s3 selftest: ok")


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "selftest" and not args:
        selftest()
    elif cmd == "put" and len(args) == 2:
        status, body = request("PUT", args[1], upload=args[0])
        if status != 200:
            sys.exit(f"backup_s3: PUT {args[1]} → HTTP {status}: {body[:500]!r}")
    elif cmd == "get" and len(args) == 2:
        status, body = request("GET", args[0], download=args[1])
        if status != 200:
            sys.exit(f"backup_s3: GET {args[0]} → HTTP {status}: {body[:500]!r}")
    elif cmd == "list" and args[:1] == ["-l"] and len(args) <= 2:
        for modified, key in list_keys(args[1] if len(args) > 1 else "", with_time=True):
            print(f"{modified}\t{key}")
    elif cmd == "list" and len(args) <= 1:
        print("\n".join(list_keys(args[0] if args else "")))
    elif cmd == "latest" and len(args) == 1:
        keys = list_keys(args[0])
        if not keys:
            sys.exit(f"backup_s3: в {args[0]} пусто")
        print(keys[-1])
    elif cmd == "check-write-only" and not args:
        check_write_only()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
