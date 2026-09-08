# noqa: E501
import sys
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from worksheet_corpus.store import load_draft, save_draft

I = []


def add(did, i, answer, solution, warning=''):
    I.append({'id': did, 'i': i, 'answer': answer, 'solution': solution,
              'warning': warning})


def apply_one(did):
    draft = load_draft(did)
    if not draft:
        print(f'MISS {did}', file=sys.stderr)
        return 0
    els = draft.get('elements') or []
    n = 0
    for row in I:
        if row['id'] != did:
            continue
        i = row['i']
        el = els[i]
        if el.get('kind') != 'task' or el.get('skip'):
            print(f'SKIP {did}#{i}', file=sys.stderr)
            continue
        el['answer'] = row['answer']
        el['solution'] = row['solution']
        el['answer_origin'] = 'neuro'
        warn = (row.get('warning') or '').strip()
        if warn:
            warns = list(el.get('warnings') or [])
            if warn not in warns:
                warns.append(warn)
            el['warnings'] = warns
        n += 1
    save_draft(draft)
    print(f'SAVED {did} n={n}')
    return n


D = '9 класс/matvert9-lim'
add(D, 0,
    r'$\dfrac{3}{2}$, $\dfrac{5}{3}$, $\dfrac{7}{4}$, $\dfrac{9}{5}$, $\dfrac{11}{6}$, $\dfrac{13}{7}$; $\dfrac{201}{101}$; $\dfrac{4045}{2023}$; предел $2$',
    r'''$a_n=\frac{2n+1}{n+1}$.
$a_1=\frac{3}{2}$, $a_2=\frac{5}{3}$, $a_3=\frac{7}{4}$, $a_4=\frac{9}{5}$, $a_5=\frac{11}{6}$, $a_6=\frac{13}{7}$,
$a_{100}=\frac{201}{101}$, $a_{2022}=\frac{4045}{2023}$.
$a_n=\frac{2+\frac{1}{n}}{1+\frac{1}{n}}\to 2$.
Ответ: $\frac{3}{2}$, $\frac{5}{3}$, $\frac{7}{4}$, $\frac{9}{5}$, $\frac{11}{6}$, $\frac{13}{7}$; $\frac{201}{101}$; $\frac{4045}{2023}$; предел $2$.''')
add(D, 1,
    r'доказано',
    r'''Нужно для любого $\varepsilon>0$ указать $N$ такое, что при $n>N$ верно $\bigl|\frac{(-1)^n}{n}\bigr|<\varepsilon$.
Но $\bigl|\frac{(-1)^n}{n}\bigr|=\frac{1}{n}$, поэтому достаточно взять $N=\bigl\lceil\frac{1}{\varepsilon}\bigr\rceil$. Тогда при $n>N$ имеем $\frac{1}{n}<\varepsilon$.
Ответ: доказано.''')
add(D, 2,
    r'доказано',
    r'''Пусть $\lim x_n=a$ и $\lim x_n=b$, причём $a\neq b$. Положим $\varepsilon=\frac{|a-b|}{2}>0$. Для достаточно больших $n$ одновременно $|x_n-a|<\varepsilon$ и $|x_n-b|<\varepsilon$, откуда $|a-b|\le |a-x_n|+|x_n-b|<2\varepsilon=|a-b|$, противоречие. Значит, предел единствен.
Ответ: доказано.''')
add(D, 3,
    r'доказано',
    r'''Если $x_n=b$ при всех $n$, то $|x_n-b|=0<\varepsilon$ для любого $\varepsilon>0$ и любого $N$. Поэтому $\lim x_n=b$.
Ответ: доказано.''')
add(D, 4,
    r'доказано',
    r'''Пусть $\lim x_n=b$. Для $\varepsilon=1$ найдётся $N$ такое, что при $n>N$ верно $|x_n-b|<1$, то есть эти члены лежат на $(b-1;b+1)$. Конечный набор $x_1,\ldots,x_N$ ограничен. Значит, вся последовательность ограничена.
Ответ: доказано.''')
add(D, 5,
    r'доказано (для частного при $\lim b_n\neq 0$)',
    r'''Пусть $a_n\to a$, $b_n\to b$.
Сумма: $|(a_n+b_n)-(a+b)|\le |a_n-a|+|b_n-b|\to 0$.
Произведение: $a_nb_n-ab=a_n(b_n-b)+b(a_n-a)$; сходящаяся последовательность $a_n$ ограничена, поэтому правая часть стремится к нулю.
Частное: если $b\neq 0$, то при больших $n$ имеем $|b_n|\ge\frac{|b|}{2}$, и $\bigl|\frac{a_n}{b_n}-\frac{a}{b}\bigr|=\frac{|a_nb-ab_n|}{|b_n||b|}\to 0$.
Ответ: доказано (для частного при $\lim b_n\neq 0$).''',
    'В формулировке свойства не оговорено $b_n\\to b\\neq 0$ для частного.')
add(D, 6,
    r'нет; да, $0$; да, $0$; да, $2$',
    r'''а) $a_n=3n\to\infty$, последовательность расходится.
б) $a_n=\frac{1}{3n}\to 0$, сходится.
в) Члены $\pm\frac{1}{n}$ стремятся к нулю, поэтому последовательность сходится к $0$.
г) Постоянная последовательность сходится к $2$.
Ответ: нет; да, $0$; да, $0$; да, $2$.''')
add(D, 7,
    r'$0$; $0$; $2$; нет; нет; $0$',
    r'''а) $\frac{1}{2^{n-1}}\to 0$.
б) $\frac{1}{3n}\to 0$.
в) $\frac{2n-1}{n}\to 2$.
г) Подпоследовательности чётных и нечётных номеров стремятся к $1$ и $-1$, предела нет.
д) $\frac{(-1)^n n}{n+1}$ имеет предельные точки $1$ и $-1$, предела нет.
е) $\frac{1}{n!}\to 0$.
Ответ: $0$; $0$; $2$; нет; нет; $0$.''')
add(D, 8,
    r'$2$',
    r'''$\frac{4n-1}{2n+3}=\frac{4-\frac{1}{n}}{2+\frac{3}{n}}\to\frac{4}{2}=2$.
Ответ: $2$.''')
add(D, 9,
    r'$3$',
    r'''$\frac{3n^2+1}{n^2}=3+\frac{1}{n^2}\to 3$.
Ответ: $3$.''')
add(D, 10,
    r'$-1$',
    r'''$\frac{-n^2-3n-1}{n^2-2n-1}=\frac{-1-\frac{3}{n}-\frac{1}{n^2}}{1-\frac{2}{n}-\frac{1}{n^2}}\to -1$.
Ответ: $-1$.''')
add(D, 11,
    r'$\dfrac{1}{3}$',
    r'''$1+3+\ldots+(2n-1)=n^2$, поэтому $\frac{n^2}{3n^2}=\frac{1}{3}$.
Ответ: $\frac{1}{3}$.''')
add(D, 12,
    r'$\dfrac{1}{2}$',
    r'''Разделим числитель и знаменатель на $4^n$: $\frac{3\cdot\bigl(\frac{3}{4}\bigr)^n+2}{4-\frac{5}{4^n}}\to\frac{2}{4}=\frac{1}{2}$.
Ответ: $\frac{1}{2}$.''')
add(D, 13,
    r'$0$',
    r'''$\frac{\sqrt{n}}{n+1}=\frac{1}{\sqrt{n}+\frac{1}{\sqrt{n}}}\to 0$.
Ответ: $0$.''')
add(D, 14,
    r'$2$',
    r'''Умножим на сопряжённое: $\frac{(n^2+2n+3)-(n^2-2n+5)}{\sqrt{n^2+2n+3}+\sqrt{n^2-2n+5}}=\frac{4n-2}{\sqrt{n^2+2n+3}+\sqrt{n^2-2n+5}}\to\frac{4}{2}=2$.
Ответ: $2$.''')
add(D, 15,
    r'$-3$',
    r'''$(n-3)(5-6n)=-6n^2+23n-15$, поэтому $\frac{-6n^2+23n-15}{2n^2+5}\to-\frac{6}{2}=-3$.
Ответ: $-3$.''')
add(D, 16,
    r'$0$',
    r'''$n^2+n-2=(n+2)(n-1)$, значит $\frac{2n-1}{(n+2)(n-1)}-\frac{1}{n-1}=\frac{n-3}{(n+2)(n-1)}\to 0$.
Ответ: $0$.''')
add(D, 17,
    r'$3$',
    r'''$(n-1)^3+(2-n)^3=(n-1)^3-(n-2)^3=(n-1)^2+(n-1)(n-2)+(n-2)^2=3n^2-9n+7$.
Тогда $\frac{3n^2-9n+7}{n^2-n+2}\to 3$.
Ответ: $3$.''')
add(D, 18,
    r'$0$; $\dfrac{3}{2}$; $-\dfrac{1}{4}$; $1$; $\dfrac{4}{3}$; $\dfrac{3}{2}$; $2$',
    r'''а) Степень знаменателя выше, предел $0$.
б) $\frac{3n+2}{2n+1}\to\frac{3}{2}$.
в) $\frac{n^2-11n+3}{3-2n-4n^2}\to-\frac{1}{4}$.
г) $\frac{(n^2+n+3)-(n^2-n+5)}{\sqrt{n^2+n+3}+\sqrt{n^2-n+5}}=\frac{2n-2}{\ldots}\to 1$.
д) $\frac{4n^3+3n+1}{3n^3+n^2+4}\to\frac{4}{3}$.
е) $\frac{1}{n}+\frac{3n+1}{2n-1}\to\frac{3}{2}$.
ж) $\frac{(n+3)(2n-1)}{n^2-n+2}=\frac{2n^2+5n-3}{n^2-n+2}\to 2$.
Ответ: $0$; $\frac{3}{2}$; $-\frac{1}{4}$; $1$; $\frac{4}{3}$; $\frac{3}{2}$; $2$.''')
add(D, 19,
    r'$\dfrac{1}{2}$',
    r'''Ряд есть $\sum_{n=1}^{\infty}\bigl(\frac{1}{2^n}-\frac{1}{3^n}\bigr)$. Обе геометрические прогрессии сходятся абсолютно, поэтому сумма равна $\frac{1/2}{1-1/2}-\frac{1/3}{1-1/3}=1-\frac{1}{2}=\frac{1}{2}$.
Ответ: $\frac{1}{2}$.''')

D = '9 класс/matvert9-sr-lim'
add(D, 0,
    r'$\dfrac{1}{4}$',
    r'''$\frac{n+1}{4n+2}=\frac{1+\frac{1}{n}}{4+\frac{2}{n}}\to\frac{1}{4}$.
Ответ: $\frac{1}{4}$.''')
add(D, 1,
    r'$-1$',
    r'''$\frac{n^2-n}{7-2n-n^2}\to\frac{1}{-1}=-1$.
Ответ: $-1$.''')
add(D, 2,
    r'$\dfrac{3}{2}$',
    r'''Сумма $2+5+\ldots+(3n-1)$ есть $n$ членов арифметической прогрессии: $\frac{n(2+3n-1)}{2}=\frac{n(3n+1)}{2}$.
Тогда $\frac{3n^2+n}{2(n^2+n+2)}\to\frac{3}{2}$.
Ответ: $\frac{3}{2}$.''')
add(D, 3,
    r'$-\dfrac{4}{3}$',
    r'''$\frac{3-4n}{2+3n}\to-\frac{4}{3}$.
Ответ: $-\frac{4}{3}$.''')
add(D, 4,
    r'$-2$',
    r'''$\frac{2n^2-3n+11}{9-4n-n^2}\to-2$.
Ответ: $-2$.''')
add(D, 5,
    r'$-\dfrac{3}{4}$',
    r'''$1+7+\ldots+(6n-5)=\frac{n(1+6n-5)}{2}=n(3n-2)=3n^2-2n$.
Тогда $\frac{3n^2-2n}{3+7n-4n^2}\to-\frac{3}{4}$.
Ответ: $-\frac{3}{4}$.''')
add(D, 6,
    r'$-\dfrac{4}{3}$',
    r'''$\frac{3-4n}{2+3n}\to-\frac{4}{3}$.
Ответ: $-\frac{4}{3}$.''')
add(D, 7,
    r'$\dfrac{17}{4}$',
    r'''$\sqrt{4n^2+5n-3}-2n=\frac{5n-3}{\sqrt{4n^2+5n-3}+2n}\to\frac{5}{4}$.
Значит, $\sqrt{4n^2+5n-3}-2n+3\to\frac{5}{4}+3=\frac{17}{4}$.
Ответ: $\frac{17}{4}$.''')
add(D, 8,
    r'$-\dfrac{3}{4}$',
    r'''Сумма числителя равна $3n^2-2n$, предел $\frac{3n^2-2n}{3+7n-4n^2}=-\frac{3}{4}$.
Ответ: $-\frac{3}{4}$.''')

if __name__ == '__main__':
    for did in ['9 класс/matvert9-lim', '9 класс/matvert9-sr-lim']:
        apply_one(did)
