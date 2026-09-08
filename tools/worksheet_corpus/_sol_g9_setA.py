# noqa: E501
"""Ответы 9-классного набора (prop_otr, замена, Менелай/Чева). Не коммитить."""
import sys
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from worksheet_corpus._apply_agent_solutions import apply_solutions
from worksheet_corpus.store import load_draft

I = []


def add(did, i, answer, solution, warning=''):
    I.append({'id': did, 'i': i, 'answer': answer, 'solution': solution,
              'warning': warning})


# ---------------------------------------------------------------------------
# КР пропорциональные отрезки
# ---------------------------------------------------------------------------
D = '9 класс/КР 9 класс геометрия/matvert9-kr2-prop_otr-2022'

add(D, 0, r'$33$',
    r'''$MN\parallel AC$, поэтому $\triangle BMN\sim\triangle BAC$ и $\dfrac{BN}{BC}=\dfrac{MN}{AC}=\dfrac{15}{25}=\dfrac{3}{5}$.
$BC=BN+22$, откуда $BN=\dfrac{3}{5}(BN+22)$, $2BN=66$, $BN=33$.
Ответ: $33$.''')

add(D, 1, r'$15$ и $20$',
    r'''$AH^2=BH\cdot HC$. Пусть $BH=9k$, $HC=16k$. Тогда $144=144k^2$, $k=1$, $BH=9$, $HC=16$, $BC=25$.
Катеты: $AB=\sqrt{BH\cdot BC}=15$, $AC=\sqrt{HC\cdot BC}=20$.
Ответ: $15$ и $20$.''')

add(D, 2, r'$17$',
    r'''Четырёхугольник $KBCP$ вписанный, поэтому $\triangle AKP\sim\triangle ACB$ (общий угол $A$ и равные углы, опирающиеся на одну дугу).
$\dfrac{KP}{BC}=\dfrac{AP}{AB}$. Но $BC=\dfrac{1}{2}AB$, значит $KP=\dfrac{1}{2}AP=17$.
Ответ: $17$.''')

add(D, 3, r'$7$, $\dfrac{11}{5}$, $\dfrac{42}{5}$',
    r'''$\angle BAF=\angle C$. В $\triangle ABF$ углы равны $C$, $B$ и $A$, поэтому $\triangle ABF\sim\triangle CBA$.
$\dfrac{AB}{CB}=\dfrac{BF}{BA}=\dfrac{AF}{CA}$, $\dfrac{6}{5}=\dfrac{BF}{6}=\dfrac{AF}{7}$.
$BF=\dfrac{36}{5}$, $AF=\dfrac{42}{5}$. Точка $F$ лежит на луче $BC$ за $C$, $CF=\dfrac{36}{5}-5=\dfrac{11}{5}$.
Стороны $\triangle ACF$: $AC=7$, $CF=\dfrac{11}{5}$, $AF=\dfrac{42}{5}$.
Ответ: $7$, $\dfrac{11}{5}$, $\dfrac{42}{5}$.''')

add(D, 4, r'$32$; $20$',
    r'''$AN\cdot NB=DN\cdot NC=16{,}5\cdot 14=231$, $AN=NB+10$.
$(t+10)t=231$, $t^2+10t-231=0$, $t=11$, $AN=21$, $AB=32$.
Для внутренней точки $AN\cdot NB=R^2-ON^2$, $231=R^2-169$, $R=20$.
Ответ: $32$; $20$.''')

add(D, 5, r'$\dfrac{3}{7}$',
    r'''Биссектриса угла $A$ параллелограмма отсекает равнобедренный $\triangle ABM$: $\angle AMB=\angle DAM$ (накрест лежащие при $AD\parallel BC$), поэтому $AB=BM$.
$BM:MC=2:3$, значит $AB:AD=2:5$ (ведь $AD=BC=BM+MC$).
Биссектрисы противоположных углов $A$ и $C$ высекают на $BD$ точки $P$ и $T$, симметричные относительно середины $BD$.
$BP:PD=AB:AD=2:5$, $BT:TD=5:2$, откуда $PT=\dfrac{3}{7}BD$.
Ответ: $\dfrac{3}{7}$.''')

add(D, 6, r'$3$ или $17$',
    r'''Хорда $48$ в окружности радиуса $25$ удалена от центра на $\sqrt{25^2-24^2}=7$, в окружности радиуса $26$ — на $\sqrt{26^2-24^2}=10$.
Центры по одну сторону от хорды: расстояние $|10-7|=3$; по разные стороны: $10+7=17$.
Ответ: $3$ или $17$.''')

add(D, 7, r'$35$',
    r'''$AB\parallel DC$, поэтому $\triangle AMB\sim\triangle CMD$ и $\dfrac{AM}{CM}=\dfrac{AB}{CD}=\dfrac{13}{65}=\dfrac{1}{5}$.
$AM+CM=42$, $AM=7$, $CM=35$.
Ответ: $35$.''')

add(D, 8, r'$27\sqrt{3}$',
    r'''$BK^2=AK\cdot KC$. Пусть $AK=3k$, $KC=4k$, тогда $AC=7k$ и катеты $AB=k\sqrt{21}$, $BC=2k\sqrt{7}$.
Меньший катет $AB=9$, $k=\dfrac{9}{\sqrt{21}}$, $S=\dfrac{1}{2}\cdot 9\cdot 2k\sqrt{7}=27\sqrt{3}$.
Ответ: $27\sqrt{3}$.''')

add(D, 9, r'$\dfrac{12}{7}$',
    r'''$\triangle AKP\sim\triangle ACB$, поэтому $\dfrac{KP}{BC}=\dfrac{AK}{AC}$.
$AC=3{,}5\,BC$, $KP=\dfrac{6}{3{,}5}=\dfrac{12}{7}$.
Ответ: $\dfrac{12}{7}$.''')

add(D, 10, r'$\dfrac{39}{5}$, $9$, $\dfrac{72}{5}$',
    r'''$\angle KCA=\angle B$. В $\triangle AKC$ углы $A$, $C$ и $B$, поэтому $\triangle AKC\sim\triangle ACB$.
$\dfrac{AK}{AC}=\dfrac{KC}{CB}=\dfrac{AC}{AB}$, $\dfrac{AK}{8}=\dfrac{KC}{9}=\dfrac{8}{5}$.
$AK=\dfrac{64}{5}$, $KC=\dfrac{72}{5}$. Точка $K$ на луче $AB$ за $B$, $KB=\dfrac{64}{5}-5=\dfrac{39}{5}$.
Ответ: $\dfrac{39}{5}$, $9$, $\dfrac{72}{5}$.''')

add(D, 11, r'$14$; $7$',
    r'''$AM\cdot MB=6\cdot 4=24=(x+10)x$, $x^2+10x-24=0$, $x=2$, $DM=12$, $DC=14$.
$R^2-OM^2=24$, $R^2-25=24$, $R=7$.
Ответ: $14$; $7$.''')

add(D, 12, r'$22{,}5^{\circ}$ и $67{,}5^{\circ}$',
    r'''$S=\dfrac{1}{2}c^2\sin\theta\cos\theta=100\sin\theta\cos\theta=50\sin 2\theta=50\sqrt{2}$, $\sin 2\theta=\dfrac{\sqrt{2}}{2}$.
$2\theta=45^{\circ}$ или $135^{\circ}$, острые углы $22{,}5^{\circ}$ и $67{,}5^{\circ}$.
Ответ: $22{,}5^{\circ}$ и $67{,}5^{\circ}$.''')

add(D, 13, r'$\dfrac{99}{247}$',
    r'''Барицентрические координаты: $M=\bigl(\frac12;0;\frac12\bigr)$, $K=\bigl(\frac{7}{26};\frac{12}{26};\frac{7}{26}\bigr)$.
Прямая $AK$ пересекает $BC$ в $P=\bigl(0;\frac{12}{19};\frac{7}{19}\bigr)$, $BP:PC=7:12$.
$S_{KMC}=\dfrac{3}{13}S$, $S_{KPC}=\dfrac{42}{247}S$, $S_{KPCM}=\dfrac{99}{247}S$.
Ответ: $\dfrac{99}{247}$.''')

add(D, 14, r'$39$',
    r'''$\dfrac{AM}{CM}=\dfrac{14}{42}=\dfrac{1}{3}$, $AM+CM=52$, $CM=39$.
Ответ: $39$.''')

add(D, 15, r'$\dfrac{27\sqrt{6}}{2}$',
    r'''Пусть $AH=2k$, $HB=3k$. Катеты $AC=k\sqrt{10}$, $BC=k\sqrt{15}$.
Больший катет $BC=9$, $k=\dfrac{9}{\sqrt{15}}$, $S=\dfrac{1}{2}k\sqrt{10}\cdot 9=\dfrac{27\sqrt{6}}{2}$.
Ответ: $\dfrac{27\sqrt{6}}{2}$.''')

add(D, 16, r'$\dfrac{28}{5}$',
    r'''$\triangle AKP\sim\triangle ACB$, $\dfrac{KP}{BC}=\dfrac{AK}{AC}$, $AC=2{,}5\,BC$, $KP=\dfrac{14}{2{,}5}=\dfrac{28}{5}$.
Ответ: $\dfrac{28}{5}$.''')

add(D, 17, r'$\dfrac{16}{3}$, $\dfrac{10}{3}$, $8$',
    r'''$\angle BAD=\angle C$. В $\triangle ABD$ углы $C$, $B$, $A$, поэтому $\triangle ABD\sim\triangle CBA$.
$\dfrac{AB}{CB}=\dfrac{BD}{BA}=\dfrac{AD}{CA}$, $\dfrac{4}{6}=\dfrac{BD}{4}=\dfrac{AD}{8}$.
$BD=\dfrac{8}{3}$, $AD=\dfrac{16}{3}$, $DC=6-\dfrac{8}{3}=\dfrac{10}{3}$.
Ответ: $\dfrac{16}{3}$, $\dfrac{10}{3}$, $8$.''')

add(D, 18, r'$20$; $10$',
    r'''$12\cdot 3=36=(x+16)x$, $x=2$, $DM=18$, $DC=20$.
$R^2-64=36$, $R=10$.
Ответ: $20$; $10$.''')

add(D, 19, r'$15^{\circ}$ и $75^{\circ}$',
    r'''$S=196\sin\theta\cos\theta=98\sin 2\theta=98$, $\sin 2\theta=\dfrac12$, $2\theta=30^{\circ}$ или $150^{\circ}$.
Ответ: $15^{\circ}$ и $75^{\circ}$.''')

add(D, 20, r'$\dfrac{25}{99}$',
    r'''$K=\bigl(\frac{7}{18};\frac{4}{18};\frac{7}{18}\bigr)$, $P=\bigl(0;\frac{4}{11};\frac{7}{11}\bigr)$.
$S_{KMC}=\dfrac19 S$, $S_{KPC}=\dfrac{14}{99}S$, сумма $\dfrac{25}{99}S$.
Ответ: $\dfrac{25}{99}$.''')


# ---------------------------------------------------------------------------
# Замена (sr-t_menelaytex)
# ---------------------------------------------------------------------------
E = '9 класс/matvert9-sr-t_menelaytex'

add(E, 0,
    r'$\dfrac{C_{70}^{3}C_{50}^{5}}{C_{120}^{8}}$; $\dfrac{C_{70}^{2}C_{50}^{6}}{C_{120}^{8}}$; $\dfrac{C_{50}^{8}}{C_{120}^{8}}$',
    r'''Гипергеометрическая схема: $120$ учеников, среди них $70$ знакомых, выбирают $8$.
$P(X=k)=\dfrac{C_{70}^{k}C_{50}^{8-k}}{C_{120}^{8}}$.
а) $k=3$; б) $k=2$; в) $k=0$.
Ответ: $\dfrac{C_{70}^{3}C_{50}^{5}}{C_{120}^{8}}$; $\dfrac{C_{70}^{2}C_{50}^{6}}{C_{120}^{8}}$; $\dfrac{C_{50}^{8}}{C_{120}^{8}}$.''')

add(E, 1, r'$120$',
    r'''Каждому из четырёх учеников — своя тема, повторы запрещены: $P_{5}^{4}=5\cdot 4\cdot 3\cdot 2=120$.
Ответ: $120$.''')

add(E, 2,
    r'$S=6\sqrt{14}$; $h_5=\dfrac{12\sqrt{14}}{5}$, $h_9=\dfrac{4\sqrt{14}}{3}$, $h_{10}=\dfrac{6\sqrt{14}}{5}$; $m_5=\dfrac{\sqrt{337}}{2}$, $m_9=\dfrac{13}{2}$, $m_{10}=2\sqrt{7}$',
    r'''$p=12$, $S=\sqrt{12\cdot 7\cdot 3\cdot 2}=6\sqrt{14}$.
Высоты $h_a=\dfrac{2S}{a}$: $\dfrac{12\sqrt{14}}{5}$, $\dfrac{4\sqrt{14}}{3}$, $\dfrac{6\sqrt{14}}{5}$.
Медианы $m_a=\dfrac12\sqrt{2b^2+2c^2-a^2}$: $m_5=\dfrac{\sqrt{337}}{2}$, $m_9=\dfrac{13}{2}$, $m_{10}=2\sqrt{7}$.
Ответ: $S=6\sqrt{14}$; высоты $\dfrac{12\sqrt{14}}{5}$, $\dfrac{4\sqrt{14}}{3}$, $\dfrac{6\sqrt{14}}{5}$; медианы $\dfrac{\sqrt{337}}{2}$, $\dfrac{13}{2}$, $2\sqrt{7}$.''')

add(E, 3, r'$(-\infty;-1)\cup\bigl(0;\frac{2}{5}\bigr)$',
    r'''$\dfrac{2-3x-5x^2}{x^3}>0$, $\dfrac{(5x-2)(x+1)}{x^3}<0$.
Точки $-1$, $0$, $\dfrac{2}{5}$. Метод интервалов: $(-\infty;-1)\cup\bigl(0;\frac{2}{5}\bigr)$.
Ответ: $(-\infty;-1)\cup\bigl(0;\frac{2}{5}\bigr)$.''')

add(E, 4, r'$a\in\bigl(-1;\frac{3}{2}\bigr)$',
    r'''$x^2+2(a-1)x+(4-a-a^2)>0$ при всех $x$ $\Leftrightarrow$ $D<0$.
$D=4\bigl(2a^2-a-3\bigr)=4(2a-3)(a+1)$.
$D<0$ при $a\in\bigl(-1;\frac{3}{2}\bigr)$.
Ответ: $a\in\bigl(-1;\frac{3}{2}\bigr)$.''')


# ---------------------------------------------------------------------------
# sr-t_menelay
# ---------------------------------------------------------------------------
F = '9 класс/matvert9-sr-t_menelay'

add(F, 0, r'$1:4$',
    r'''Пусть $OA=AB=1$, $OC=1$, $CD=2$. Тогда $A=\mathbf{u}$, $B=2\mathbf{u}$, $C=\mathbf{v}$, $D=3\mathbf{v}$.
Прямая $AD$: $(1-s)\mathbf{u}+3s\mathbf{v}$; прямая $BC$: $2(1-t)\mathbf{u}+t\mathbf{v}$.
Из равенства $1-s=2(1-t)$, $3s=t$ получаем $s=\dfrac{1}{5}$.
Точка $P=(1-s)A+sD$ делит $AD$ в отношении $AP:PD=1:4$.
Менелай в $\triangle OAD$ для секущей $BPC$: $\dfrac{OB}{BA}\cdot\dfrac{AP}{PD}\cdot\dfrac{DC}{CO}=1$, $\dfrac{AP}{PD}=\dfrac{1}{4}$.
Ответ: $1:4$.''')

add(F, 1, r'$\dfrac{27}{8}$',
    r'''В $\triangle ABC$ секущая $FED$: $F$ на $AB$ ($AF=4$, $FB=2$), $E$ на $BC$ ($BE=4{,}5$, $EC=x$), $D$ на продолжении $AC$ за $C$ ($AC=5$, $CD=3$).
Теорема Менелая (направленные отрезки): $\dfrac{AF}{FB}\cdot\dfrac{BE}{EC}\cdot\dfrac{CD}{DA}=1$ с учётом знака даёт
$\dfrac{4}{2}\cdot\dfrac{4{,}5}{x}\cdot\dfrac{3}{8}=1$, $x=\dfrac{27}{8}$.
Ответ: $\dfrac{27}{8}$.''')

add(F, 2, r'$3:2$',
    r'''$BK:CK=1:2$, $M$ — середина $AB$. В барицентрических координатах $K=\bigl(0;\frac{2}{3};\frac{1}{3}\bigr)$, $M=\bigl(\frac{1}{2};\frac{1}{2};0\bigr)$.
Прямые $AK$ и $CM$ пересекаются в $O=\bigl(\frac{2}{5};\frac{2}{5};\frac{1}{5}\bigr)$.
Прямая $BO$ пересекает $AC$ в $E=\bigl(\frac{2}{3};0;\frac{1}{3}\bigr)$.
$O=(1-\lambda)B+\lambda E$ с $\lambda=\dfrac{3}{5}$, поэтому $BO:OE=3:2$.
Ответ: $3:2$.''')

add(F, 3, r'противоречие: $\dfrac{AK}{KB}=\dfrac{AK_1}{K_1B}$',
    r'''По теореме Менелая для прямой $MLK_1$: $\dfrac{AK_1}{K_1B}\cdot\dfrac{BL}{LC}\cdot\dfrac{CM}{MA}=1$.
По условию $\dfrac{AK}{KB}\cdot\dfrac{BL}{LC}\cdot\dfrac{CM}{MA}=1$.
Значит $\dfrac{AK}{KB}=\dfrac{AK_1}{K_1B}$. Функция $f(X)=\dfrac{AX}{XB}$ строго монотонна на прямой $AB$, поэтому $K=K_1$ — противоречие.
Ответ: противоречие: $\dfrac{AK}{KB}=\dfrac{AK_1}{K_1B}$.''')

add(F, 4, r'доказано',
    r'''$AK:KB=3:2$, $CL:LA=1:3$ (от $C$, то есть $CL:LA=1:3$, $AL:LC=3:1$).
$C$ — середина $MB$, $MC=CB$, направленно $\dfrac{CM}{MB}=\dfrac12$ по длине, но $M$ за $C$, $\dfrac{BM}{MC}=2$ и $\dfrac{CM}{MA}$ на прямой $BC$.
Теорема Менелая (обратная) для $K,L,M$:
$\dfrac{AK}{KB}\cdot\dfrac{BL}{LC}\cdot\dfrac{CM}{MA}$.
$L$ на $AC$, $AL:LC=3:1$, $M$ на прямой $BC$, $B$–$C$–$M$, $BC=CM$, $\dfrac{BL}{LC}$ — $L$ не на $BC$.
Правильно: $K$ на $AB$, $L$ на $AC$, $M$ на $BC$.
$\dfrac{AK}{KB}\cdot\dfrac{BM}{MC}\cdot\dfrac{CL}{LA}=\dfrac{3}{2}\cdot\dfrac{2}{1}\cdot\dfrac{1}{3}=1$.
Две точки на сторонах, одна на продолжении — точки $K$, $L$, $M$ коллинеарны.
Ответ: доказано.''')

add(F, 5, r'$3:2$',
    r'''Как в варианте 1: $A=\mathbf{u}$, $B=2\mathbf{u}$, $C=\mathbf{v}$, $D=3\mathbf{v}$.
Пересечение $AD$ и $BC$ при $t=\dfrac{3}{5}$ на $BC$, поэтому $BP:PC=3:2$.
Ответ: $3:2$.''')

add(F, 6, r'$\dfrac{27}{8}$',
    r'''Рисунок варианта 2 того же типа, что в варианте 1 (подписи длин те же по смыслу секущей Менелая). Если числа на чертеже совпадают с вариантом 1, $x=\dfrac{27}{8}$.
Ответ: $\dfrac{27}{8}$.''',
    'Длины на pic2-v2 сняты как у варианта 1; если чертёж другой, ответ нужно сверить по рисунку.')

add(F, 7, r'$3:2$',
    r'''Та же конфигурация, что в задаче 3 варианта 1: $BO:OE=3:2$.
Ответ: $3:2$.''')

add(F, 8, r'противоречие: $\dfrac{AK}{KB}=\dfrac{AK_1}{K_1B}$',
    r'''Как в варианте 1: две записи теоремы Менелая дают $\dfrac{AK}{KB}=\dfrac{AK_1}{K_1B}$, откуда $K=K_1$.
Ответ: противоречие: $\dfrac{AK}{KB}=\dfrac{AK_1}{K_1B}$.''')

add(F, 9, r'доказано',
    r'''$AK:KB=3:4$, $L$ делит $AC$ в отношении $2:3$ от $C$, то есть $CL:LA=2:3$, $AL:LC=3:2$.
$C$ — середина $MB$, $BM:MC=2:1$ направленно $B$–$C$–$M$, $BC=CM$.
$\dfrac{AK}{KB}\cdot\dfrac{BM}{MC}\cdot\dfrac{CL}{LA}=\dfrac{3}{4}\cdot 2\cdot\dfrac{2}{3}=1$.
По обратной теореме Менелая точки $M$, $L$, $K$ коллинеарны.
Ответ: доказано.''')


if __name__ == '__main__':
    apply_solutions(I)
    ids = [
        '9 класс/КР 9 класс геометрия/matvert9-kr2-prop_otr-2022',
        '9 класс/matvert9-sr-t_menelaytex',
        '9 класс/matvert9-sr-t_menelay',
    ]
    for did in ids:
        d = load_draft(did)
        holes = []
        ok = 0
        for i, el in enumerate(d.get('elements') or []):
            if el.get('kind') != 'task' or el.get('skip'):
                continue
            if (el.get('answer') or '').strip() and (el.get('solution') or '').strip():
                ok += 1
            else:
                holes.append(i)
        print(f'REPORT {did} ok={ok} holes={holes}')
