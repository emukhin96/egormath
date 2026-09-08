# noqa: E501
"""Ответы/решения для черновиков 9 класса (Менелай, Чева, КР). Не коммитить."""
import sys
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from worksheet_corpus._apply_agent_solutions import apply_solutions

I = []
def add(did, i, answer, solution, warning=''):
    I.append({'id': did, 'i': i, 'answer': answer, 'solution': solution,
              'warning': warning})


def menelay_pair(did):
    add(did, 1,
        r'$2$; $\dfrac{9}{5}$',
        r'''а) Теорема Менелая в $\triangle ABD$ (трансверсаль через точку на $AB$, на чевиане $AD$ и на продолжении $BD$):
$\dfrac{3{,}5}{3}\cdot\dfrac{x+7}{7}\cdot\dfrac{2}{3}=1$, откуда $x=2$.
б) Аналогично $\dfrac{5}{4}\cdot\dfrac{8}{3}\cdot\dfrac{x}{6}=1$, $x=\dfrac{9}{5}$.
Ответ: $2$; $\dfrac{9}{5}$.''')
    add(did, 2,
        r'$1:1$',
        r'''На сетке $A(0;0)$, $B(0;4)$, $C(6;0)$, трансверсаль из $(-3;0)$ через $(0;1)$.
Менелай: $\dfrac{AM}{MB}\cdot\dfrac{BD}{DC}\cdot\dfrac{CP}{PA}=\dfrac{1}{3}\cdot\dfrac{BD}{DC}\cdot 3=1$, значит $BD:DC=1:1$.
Ответ: $1:1$.''')
    add(did, 3,
        r'$2:5$',
        r'''Пусть $AC=3t$, тогда $AD=2t$ и $DC=5t$. $M$ — середина $AB$.
Менелай для $\triangle ABC$ и прямой $DMK$: $\dfrac{AM}{MB}\cdot\dfrac{BK}{KC}\cdot\dfrac{CD}{DA}=1\cdot\dfrac{BK}{KC}\cdot\dfrac{5}{2}=1$,
$BK:KC=2:5$.
Ответ: $2:5$.''')
    add(did, 4,
        r'$10:3$',
        r'''Порядок на $BL$: $B{-}N{-}M{-}L$ равными частями, иначе $M$ не лежит на $AK$.
В координатах $A(0;0)$, $B(1;0)$, $C(0;1)$ точка $K=\bigl(\frac{5}{9};\frac{4}{9}\bigr)$.
Из $M\in AK$ получаем $L\bigl(0;\frac{2}{5}\bigr)$, затем $N\in CO$ даёт $O\bigl(\frac{10}{13};0\bigr)$.
$AO:OB=10:3$.
Ответ: $10:3$.''')
    add(did, 5,
        r'$\dfrac{5}{2}$; $\dfrac{AP}{PD}=\dfrac{13}{28}$',
        r'''в) Менелай в $\triangle ABD$: $\dfrac{5}{x}\cdot\dfrac{9}{6}\cdot\dfrac{2}{6}=1$, $x=\dfrac{5}{2}$.
г) $E$ за $A$, $EA=3$, $AB=11$, $BD=7$, $DC=6$. Менелай в $\triangle ABD$:
$\dfrac{AE}{EB}\cdot\dfrac{BC}{CD}\cdot\dfrac{DP}{PA}=\dfrac{3}{14}\cdot\dfrac{13}{6}\cdot\dfrac{DP}{x}=1$, $\dfrac{AP}{PD}=\dfrac{13}{28}$.
Ответ: $\dfrac{5}{2}$; $\dfrac{AP}{PD}=\dfrac{13}{28}$.''',
        'На рисунке г не подписан второй кусок чевианы: длина $x$ не восстанавливается, есть отношение.')
    add(did, 6,
        r'$2:1$',
        r'''На сетке $B(3;5)$, $C(6;2)$, $D(5;3)$, $\overrightarrow{BD}=(2;-2)$, $\overrightarrow{DC}=(1;-1)$,
$BD:DC=2:1$. Менелай с трансверсалью $y=3$ даёт то же.
Ответ: $2:1$.''')
    add(did, 7,
        r'$5:3$',
        r'''$N$ за $C$, $CN=\frac{2}{3}AC$, $NA=\frac{5}{3}AC$. Менелай:
$\dfrac{AK}{KB}\cdot\dfrac{BP}{PC}\cdot\dfrac{CN}{NA}=\dfrac{3}{2}\cdot\dfrac{BP}{PC}\cdot\dfrac{2}{5}=1$, $BP:PC=5:3$.
Ответ: $5:3$.''')


menelay_pair('9 класс/matvert9-geom-cheva_menelay')
menelay_pair('9 класс/matvert9-geom-t_chevy')

D = '9 класс/matvert9-geom-t_chevy_only'
add(D, 1,
    r'$1:1$',
    r'''$AK:KB=1:2$, $CL:LB=1:2$, значит $BL:LC=2:1$. Третья чевиана — $BP$ (в тексте опечатка $CP$).
Чева: $\dfrac{1}{2}\cdot 2\cdot\dfrac{CM}{MA}=1$, $CM:MA=1:1$.
Ответ: $1:1$.''')
add(D, 2,
    r'$1:2$, нет',
    r'''По сетке $A(0;0)$, $B(0;5)$, $C(8;0)$, $AF:FB=2:3$, $AE:EC=1:3$.
Чева: $\dfrac{2}{3}\cdot\dfrac{BD}{DC}\cdot 3=1$, $BD:DC=1:2$.
$D=\bigl(\frac{8}{3};\frac{10}{3}\bigr)$ не на линии сетки.
Ответ: $1:2$, нет.''')
add(D, 3,
    r'нет',
    r'''$AE:EB=4:3$, $G$ — середина $BC$, $AD:DC=2:1$.
Чева: $\dfrac{4}{3}\cdot 1\cdot\dfrac{1}{2}=\dfrac{2}{3}\ne 1$. Отрезки не concurrent.
Ответ: нет.''')
add(D, 4,
    r'$1:4$',
    r'''Пусть $AF=t$, $BE=2t$, $EC=s$, $FC=2s$. Чева для $AE$, $BF$, $CD$:
$\dfrac{AD}{DB}\cdot\dfrac{2t}{s}\cdot\dfrac{2s}{t}=1$, $\dfrac{AD}{DB}=\dfrac{1}{4}$.
Ответ: $1:4$.''')
add(D, 5,
    r'$\dfrac{25}{2}$',
    r'''Биссектриса угла $B$ делит $AC$ в отношении $AB:BC=50:(25+x)$.
Чева: $\dfrac{20}{30}\cdot\dfrac{25}{x}\cdot\dfrac{25+x}{50}=1$, $\dfrac{25+x}{3x}=1$, $x=\dfrac{25}{2}$.
Ответ: $\dfrac{25}{2}$.''')
add(D, 6,
    r'нет',
    r'''$L$ — середина $AB$, $M$ — середина $BC$, $AD:DC=3:2$.
Чева: $1\cdot 1\cdot\dfrac{2}{3}\ne 1$. Не в одной точке.
Ответ: нет.''')

D = '9 класс/matvert9-geom-sr-menelaycheva'
add(D, 0,
    r'$3$',
    r'''Чева: $\dfrac{AK}{KB}\cdot\dfrac{BL}{LC}=\dfrac{MA}{CM}$. Менелай для $KLE$:
$\dfrac{MA}{CM}\cdot\dfrac{CE}{EA}=1$, $\dfrac{CE}{EA}=\dfrac{CM}{AM}=2$.
$CE=3+x$, $\dfrac{3+x}{x}=2$, $x=3$.
Ответ: $3$.''')
add(D, 1,
    r'$3:2$',
    r'''$AK:KB=BL:LC=t$. Менелай: $t^{2}\cdot\dfrac{CM}{MA}=1$, $\dfrac{CM}{MA}=\dfrac{4}{9}$, $t=\dfrac{3}{2}$.
Ответ: $3:2$.''')
add(D, 2,
    r'$\dfrac{10}{3}$',
    r'''Точка на общей хорде имеет равные степени. $8\cdot 2=3\cdot(2+x)$, $x=\dfrac{10}{3}$.
Ответ: $\dfrac{10}{3}$.''')
add(D, 3,
    r'$8$',
    r'''Центр в узле, $R=5$, хорда на прямой $y=-3$: $x^{2}+9=25$, $x=\pm 4$, длина $8$.
Ответ: $8$.''')
add(D, 4,
    r'доказано',
    r'''Внешняя касательная: $AQ=AP$, $CP=CR$, $BQ=BR$.
Чева: $\dfrac{AQ}{QB}\cdot\dfrac{BR}{RC}\cdot\dfrac{CP}{PA}=\dfrac{AP}{BQ}\cdot\dfrac{BQ}{CP}\cdot\dfrac{CP}{AP}=1$.
Ответ: доказано.''')
add(D, 5,
    r'$10$',
    r'''Как в варианте 1: $\dfrac{CE}{EA}=\dfrac{CM}{AM}=\dfrac{3}{2}$, $CE=5+x$, $x=10$.
Ответ: $10$.''')
add(D, 6,
    r'$2:1$',
    r'''$t^{2}\cdot\dfrac{1}{4}=1$, $t=2$.
Ответ: $2:1$.''')
add(D, 7,
    r'$\dfrac{3}{2}$',
    r'''Степени: $10\cdot 1=4\cdot(1+x)$, $x=\dfrac{3}{2}$.
Ответ: $\dfrac{3}{2}$.''')
add(D, 8,
    r'$6$',
    r'''По сетке хорда $AB$ лежит на линии и занимает $6$ клеток.
Ответ: $6$.''',
    'Длина снята с сетки рисунка task4v2.')
add(D, 9,
    r'доказано',
    r'''Те же касательные и Чева, что в варианте 1.
Ответ: доказано.''')

D = '9 класс/matvert9-sr-t_menelay'
add(D, 0,
    r'$1:4$',
    r'''Менелай в $\triangle OAD$ (прямая $BPC$): $\dfrac{OB}{BA}\cdot\dfrac{AP}{PD}\cdot\dfrac{DC}{CO}=2\cdot\dfrac{AP}{PD}\cdot 2=1$, $AP:PD=1:4$.
Ответ: $1:4$.''')
add(D, 1,
    r'$\dfrac{27}{8}$',
    r'''$AF:FB=2:1$, $AC:CD=5:3$, $E=BC\cap FD$. В аффинных координатах $BE:EC=4:3$.
При $BE=4{,}5$ имеем $x=\dfrac{27}{8}$.
Ответ: $\dfrac{27}{8}$.''')
add(D, 2,
    r'$3:2$',
    r'''$M$ — середина $AB$, $BK:CK=1:2$. Координаты $A(0;0)$, $B(1;0)$, $C(0;1)$ дают $O\bigl(\frac{2}{5};\frac{1}{5}\bigr)$, $E\bigl(0;\frac{1}{3}\bigr)$.
Параметр на $BOE$: $BO:OE=3:2$.
Ответ: $3:2$.''')
add(D, 3,
    r'доказано',
    r'''Менелай для $M,L,K_{1}$: $\dfrac{AK_{1}}{K_{1}B}\cdot\dfrac{BL}{LC}\cdot\dfrac{CM}{MA}=1$.
С условием $\dfrac{AK}{KB}=\dfrac{AK_{1}}{K_{1}B}$. Точка с данным отношением на $AB$ единственна, $K_{1}=K$.
Ответ: доказано.''')
add(D, 4,
    r'доказано',
    r'''$AK:KB=3:2$, $CL:LA=1:3$, $C$ — середина $MB$, $BM:MC=2$.
$\dfrac{AK}{KB}\cdot\dfrac{BM}{MC}\cdot\dfrac{CL}{LA}=\dfrac{3}{2}\cdot 2\cdot\dfrac{1}{3}=1$. Обратный Менелай.
Ответ: доказано.''')
add(D, 5,
    r'$3:2$',
    r'''Менелай в $\triangle OBC$: $\dfrac{OA}{AB}\cdot\dfrac{BP}{PC}\cdot\dfrac{CD}{DO}=1\cdot\dfrac{BP}{PC}\cdot\dfrac{2}{3}=1$, $BP:PC=3:2$.
Ответ: $3:2$.''')
add(D, 6,
    r'$\dfrac{27}{5}$',
    r'''Трансверсаль $FEC$ в $\triangle ABD$: $\dfrac{4}{2}\cdot\dfrac{4{,}5}{x}\cdot\dfrac{3}{5}=1$, $x=\dfrac{27}{5}$.
Ответ: $\dfrac{27}{5}$.''')
add(D, 7,
    r'$3:2$',
    r'''Та же конфигурация, что в варианте 1: $BO:OE=3:2$.
Ответ: $3:2$.''')
add(D, 8,
    r'доказано',
    r'''То же доказательство от противного, что в варианте 1.
Ответ: доказано.''')
add(D, 9,
    r'доказано',
    r'''$\dfrac{3}{4}\cdot 2\cdot\dfrac{2}{3}=1$. Обратный Менелай.
Ответ: доказано.''')

D = '9 класс/matvert9-sr-t_menelaytex'
add(D, 0,
    r'$\dfrac{\binom{70}{3}\binom{50}{5}}{\binom{120}{8}}$; $\dfrac{\binom{70}{2}\binom{50}{6}}{\binom{120}{8}}$; $\dfrac{\binom{50}{8}}{\binom{120}{8}}$',
    r'''Гипергеометрическое: $N=120$, знакомых $70$, в аудитории $8$.
$P(X=k)=\dfrac{\binom{70}{k}\binom{50}{8-k}}{\binom{120}{8}}$.
Ответ: $\dfrac{\binom{70}{3}\binom{50}{5}}{\binom{120}{8}}$; $\dfrac{\binom{70}{2}\binom{50}{6}}{\binom{120}{8}}$; $\dfrac{\binom{50}{8}}{\binom{120}{8}}$.''')
add(D, 1,
    r'$120$',
    r'''Размещения $P(5;4)=5\cdot 4\cdot 3\cdot 2=120$.
Ответ: $120$.''')
add(D, 2,
    r'$S=6\sqrt{14}$; $h=\dfrac{12\sqrt{14}}{5}$, $\dfrac{4\sqrt{14}}{3}$, $\dfrac{6\sqrt{14}}{5}$; $m=\dfrac{\sqrt{337}}{2}$, $\dfrac{13}{2}$, $2\sqrt{7}$',
    r'''$p=12$, $S=\sqrt{12\cdot 2\cdot 3\cdot 7}=6\sqrt{14}$.
$h_{a}=2S/a$: $\dfrac{12\sqrt{14}}{5}$, $\dfrac{4\sqrt{14}}{3}$, $\dfrac{6\sqrt{14}}{5}$.
$m_{a}=\frac12\sqrt{2b^{2}+2c^{2}-a^{2}}$: $\frac{\sqrt{337}}{2}$, $\frac{13}{2}$, $2\sqrt{7}$.
Ответ: $S=6\sqrt{14}$; $h=\dfrac{12\sqrt{14}}{5}$, $\dfrac{4\sqrt{14}}{3}$, $\dfrac{6\sqrt{14}}{5}$; $m=\dfrac{\sqrt{337}}{2}$, $\dfrac{13}{2}$, $2\sqrt{7}$.''')
add(D, 3,
    r'$x\in(-\infty;-1)\cup\bigl(0;\frac{2}{5}\bigr)$',
    r'''$\dfrac{2-3x-5x^{2}}{x^{3}}>0$, $\dfrac{(5x-2)(x+1)}{x^{3}}<0$.
Знаки на интервалах с точками $-1$, $0$, $\frac25$: решение $x<-1$ или $0<x<\frac25$.
Ответ: $x\in(-\infty;-1)\cup\bigl(0;\frac{2}{5}\bigr)$.''')
add(D, 4,
    r'$a\in\bigl(-1;\frac{3}{2}\bigr)$',
    r'''$D=4(2a^{2}-a-3)<0$, $(2a-3)(a+1)<0$, $a\in\bigl(-1;\frac{3}{2}\bigr)$.
Ответ: $a\in\bigl(-1;\frac{3}{2}\bigr)$.''')

D = '9 класс/matvert9-geom-t_o_sharnirakh'
add(D, 1,
    r'доказано',
    r'''Менелай в $\triangle OAC$ (прямая $BPD$): $\dfrac{OB}{BA}\cdot\dfrac{AP}{PC}\cdot\dfrac{CD}{DO}=\dfrac{b}{a}\cdot\dfrac{x}{y}\cdot\dfrac{d}{c+d}=1$,
откуда $\dfrac{x}{y}=\dfrac{a}{b}\bigl(\dfrac{c}{d}+1\bigr)$.
Ответ: доказано.''')
add(D, 2,
    r'$\dfrac{15}{2}$',
    r'''$OB=6$, $BA=4$, $OC=5$, $CD=4$. По теореме о шарнирах $\dfrac{AP}{PC}=\dfrac{4}{6}\bigl(\dfrac{5}{4}+1\bigr)=\dfrac{3}{2}$.
Если $PC=5$, то $x=AP=\dfrac{15}{2}$.
Ответ: $\dfrac{15}{2}$.''',
    'Числа сняты с рисунка к задаче 2; $x$ — кусок $AC$.')
add(D, 3,
    r'$3:1$ и $2:1$',
    r'''Инцентр делит биссектрису из вершины, противолежащей $a$, в отношении $(b+c):a$.
Для $3{-}4{-}5$: $9:3=3:1$ и $8:4=2:1$.
Ответ: $3:1$ и $2:1$.''')
add(D, 4,
    r'$\dfrac{7}{54}$',
    r'''$M$ — середина $AC$, $BP:PC=10:7$. В барицентрических $K=\bigl(\frac{10}{27};\frac{7}{27};\frac{10}{27}\bigr)$.
$S_{AKM}/S_{ABC}=\bigl|\det(A,K,M)\bigr|=\frac{7}{54}$.
Ответ: $\dfrac{7}{54}$.''')
add(D, 5,
    r'$\dfrac{9}{2}$',
    r'''$OB=5$, $BA=2$, $OC=3$, $CD=4{,}5$. Шарниры: $\dfrac{AP}{PC}=\dfrac{2}{5}\bigl(\dfrac{3}{4{,}5}+1\bigr)=\dfrac{2}{3}$.
$AP=3$, тогда $x=PC=\dfrac{9}{2}$.
Ответ: $\dfrac{9}{2}$.''')
add(D, 6,
    r'доказано',
    r'''$M$ — середина $BC$, $D$ на $AC$, $O=AM\cap BD$.
Барицентрически / Менелай: $\dfrac{AO}{OM}=2\dfrac{AD}{DC}$. Отношение на медиане вдвое больше отношения на $AC$.
Ответ: доказано.''')
add(D, 7,
    r'$\dfrac{1}{16}$',
    r'''$BP:PC=7:2$, $K=\bigl(\frac{7}{16};\frac{1}{8};\frac{7}{16}\bigr)$, $\det(A,K,M)=\frac{1}{16}$.
Ответ: $\dfrac{1}{16}$.''')

D = '9 класс/КР 9 класс геометрия/matvert9-kr2-prop_otr-2022'
add(D, 0,
    r'$33$',
    r'''$MN\parallel AC$, $\dfrac{BN}{BN+22}=\dfrac{15}{25}$, $BN=33$.
Ответ: $33$.''')
add(D, 1,
    r'$15$ и $20$',
    r'''$BH:HC=9:16$, $BH\cdot HC=144$, отрезки $9$ и $16$, гипотенуза $25$.
Катеты $\sqrt{9\cdot 25}=15$, $\sqrt{16\cdot 25}=20$.
Ответ: $15$ и $20$.''')
add(D, 2,
    r'$17$',
    r'''$K,B,C,P$ вписаны: $\angle AKP=\angle ACB$, $\triangle AKP\sim\triangle ACB$.
Степень: $AK\cdot AB=AP\cdot AC$ вместе с подобием даёт $AB=AC$, $KP=\frac{34}{AC}\cdot\frac{AB}{2}=17$.
Ответ: $17$.''')
add(D, 3,
    r'$AC=7$, $CF=\dfrac{11}{5}$, $AF=\dfrac{42}{5}$',
    r'''$\angle BAF=\angle C$, $\angle ABF=\angle B$, $\triangle ABF\sim\triangle CBA$.
$\frac{6}{5}=\frac{BF}{6}=\frac{AF}{7}$, $BF=\frac{36}{5}$, $AF=\frac{42}{5}$, $CF=\frac{11}{5}$.
Ответ: $AC=7$, $CF=\dfrac{11}{5}$, $AF=\dfrac{42}{5}$.''')
add(D, 4,
    r'$AB=32$, $R=20$',
    r'''$AN\cdot NB=16{,}5\cdot 14=231$, $n(n+10)=231$, $NB=11$, $AN=21$, $AB=32$.
$OM^{2}+16^{2}=R^{2}$, $MN=5$, $ON=13$, $OM=12$, $R=20$.
Ответ: $AB=32$, $R=20$.''')
add(D, 5,
    r'$\dfrac{3}{7}$',
    r'''Биссектриса угла $A$ пересекает $BC$, $BM:MC=2:3$ даёт $AB:AD=2:5$.
На $BD$ точка $P$ в отношении $2:5$ от $B$, точка $T$ (биссектриса $C$) в отношении $5:2$.
$PT=\frac{3}{7}BD$.
Ответ: $\dfrac{3}{7}$.''')
add(D, 6,
    r'$3$ или $17$',
    r'''Общая хорда $48$, половины $24$. Расстояния от центров до хорды $7$ и $10$.
Центры по одну сторону: $3$; по разные: $17$.
Ответ: $3$ или $17$.''')
add(D, 7,
    r'$35$',
    r'''$\triangle AMB\sim\triangle CMD$, $\frac{AM}{MC}=\frac{13}{65}=\frac{1}{5}$, $AM+MC=42$, $MC=35$.
Ответ: $35$.''')
add(D, 8,
    r'$27\sqrt{3}$',
    r'''$AK:KC=3:4$, меньший катет $k\sqrt{21}=9$, больший $6\sqrt{3}$, $S=27\sqrt{3}$.
Ответ: $27\sqrt{3}$.''')
add(D, 9,
    r'$\dfrac{12}{7}$',
    r'''Как выше, $AB=AC$, $KP=6\cdot BC/AB=6/(7/2)=\frac{12}{7}$.
Ответ: $\dfrac{12}{7}$.''')
add(D, 10,
    r'$KB=\dfrac{39}{5}$, $BC=9$, $KC=\dfrac{72}{5}$',
    r'''$\angle KCA=\angle B$, $\angle KAC=\angle A$, $\triangle AKC\sim\triangle ACB$.
$\frac{AK}{8}=\frac{8}{5}=\frac{KC}{9}$, $AK=\frac{64}{5}$, $K$ за $B$, $KB=\frac{39}{5}$, $KC=\frac{72}{5}$.
Ответ: $KB=\dfrac{39}{5}$, $BC=9$, $KC=\dfrac{72}{5}$.''')
add(D, 11,
    r'$DC=14$, $R=7$',
    r'''$6\cdot 4=m(m+10)$, $m=2$, $DC=14$. Степень: $R^{2}=OM^{2}+24=49$.
Ответ: $DC=14$, $R=7$.''')
add(D, 12,
    r'$22{,}5^{\circ}$ и $67{,}5^{\circ}$',
    r'''$\sin 2\alpha=\frac{2ab}{c^{2}}=\frac{\sqrt{2}}{2}$, $2\alpha=45^{\circ}$, острые $22{,}5^{\circ}$ и $67{,}5^{\circ}$.
Ответ: $22{,}5^{\circ}$ и $67{,}5^{\circ}$.''')
add(D, 13,
    r'$\dfrac{99}{247}$',
    r'''$M$ — середина $AC$, $K$ делит $BM$ как $7:6$. $P=\bigl(0;\frac{12}{19};\frac{7}{19}\bigr)$.
$S_{KPCM}=\det(K,P,C)+\det(K,C,M)=\frac{42}{247}+\frac{3}{13}=\frac{99}{247}$.
Ответ: $\dfrac{99}{247}$.''')
add(D, 14,
    r'$39$',
    r'''$\frac{AM}{MC}=\frac{14}{42}=\frac{1}{3}$, $AC=52$, $MC=39$.
Ответ: $39$.''')
add(D, 15,
    r'$\dfrac{27\sqrt{6}}{2}$',
    r'''$AH:HB=2:3$, больший катет $k\sqrt{15}=9$, меньший $3\sqrt{6}$, $S=\dfrac{27\sqrt{6}}{2}$.
Ответ: $\dfrac{27\sqrt{6}}{2}$.''')
add(D, 16,
    r'$\dfrac{28}{5}$',
    r'''$AB=AC$, $PK=14\cdot BC/AC=14/\frac{5}{2}=\frac{28}{5}$.
Ответ: $\dfrac{28}{5}$.''')
add(D, 17,
    r'$AD=\dfrac{16}{3}$, $DC=\dfrac{10}{3}$, $AC=8$',
    r'''$\triangle ABD\sim\triangle CBA$, $\frac{4}{6}=\frac{BD}{4}=\frac{AD}{8}$, $BD=\frac{8}{3}$, $AD=\frac{16}{3}$, $DC=\frac{10}{3}$.
Ответ: $AD=\dfrac{16}{3}$, $DC=\dfrac{10}{3}$, $AC=8$.''')
add(D, 18,
    r'$DC=20$, $R=10$',
    r'''$12\cdot 3=m(m+16)$, $m=2$, $DC=20$. $R^{2}=64+36=100$.
Ответ: $DC=20$, $R=10$.''')
add(D, 19,
    r'$15^{\circ}$ и $75^{\circ}$',
    r'''$\sin 2\alpha=\frac{2\cdot 196}{28^{2}}=\frac12$, острые $15^{\circ}$ и $75^{\circ}$.
Ответ: $15^{\circ}$ и $75^{\circ}$.''')
add(D, 20,
    r'$\dfrac{25}{99}$',
    r'''$BK:KM=7:2$, $P=\bigl(0;\frac{4}{11};\frac{7}{11}\bigr)$, площадь $\frac{14}{99}+\frac{1}{9}=\frac{25}{99}$.
Ответ: $\dfrac{25}{99}$.''')

D = '9 класс/КР 9 класс геометрия/matvert9-kr1-resh_treug'
add(D, 0,
    r'б, в',
    r'''а) в теореме косинусов минус, не плюс.
б) $\frac{a}{\sin A}=2R$ — верно.
в) определение тригонометрии острого угла — верно.
г) $c^{2}=49+64-56=57\ne 9$.
Ответ: б, в.''')
add(D, 1,
    r'$2-3\sqrt{3}$',
    r'''$\cos 90^{\circ}=0$, $\operatorname{tg}150^{\circ}=-\frac{1}{\sqrt{3}}$, $\sin 120^{\circ}=\frac{\sqrt{3}}{2}$, $\cos 150^{\circ}=-\frac{\sqrt{3}}{2}$, $\operatorname{ctg}135^{\circ}=-1$.
$-2\sqrt{3}+\sqrt{3}-2\sqrt{3}+2=2-3\sqrt{3}$.
Ответ: $2-3\sqrt{3}$.''')
add(D, 2,
    r'$\dfrac{3+\sqrt{3}}{2}$; $\dfrac{3+\sqrt{3}}{3}$; $3-\sqrt{3}$',
    r'''Углы $45^{\circ}$, $60^{\circ}$, $75^{\circ}$. $S=\frac{a^{2}\sin B\sin C}{2\sin A}$ при $a=2$:
против $45^{\circ}$: $\frac{3+\sqrt{3}}{2}$; против $60^{\circ}$: $\frac{3+\sqrt{3}}{3}$; против $75^{\circ}$: $3-\sqrt{3}$.
Ответ: $\dfrac{3+\sqrt{3}}{2}$; $\dfrac{3+\sqrt{3}}{3}$; $3-\sqrt{3}$.''')
add(D, 3,
    r'$\dfrac{1}{8}$; $\sqrt{154}$; $\dfrac{45\sqrt{7}}{4}$',
    r'''$DB=4$, $AD=8$, $AB=12$. В $\triangle BDC$: $\cos B=\frac{16+25-36}{40}=\frac18$.
$AC^{2}=144+25-15=154$. $\sin B=\frac{3\sqrt{7}}{8}$, $S=\frac{45\sqrt{7}}{4}$.
Ответ: $\dfrac{1}{8}$; $\sqrt{154}$; $\dfrac{45\sqrt{7}}{4}$.''')
add(D, 4,
    r'$\dfrac{25}{2}$; $\dfrac{527}{625}$; $\dfrac{22134}{625}$',
    r'''$AB=25$, $K$ — середина, $AK=\frac{25}{2}$, медиана $CK=\frac{25}{2}$, $CH=\frac{168}{25}$.
$\cos\angle HCK=\frac{336}{625}$, $\sin=\frac{527}{625}$, $S_{HCK}=\frac{22134}{625}$.
Ответ: $\dfrac{25}{2}$; $\dfrac{527}{625}$; $\dfrac{22134}{625}$.''')
add(D, 5,
    r'$\dfrac{\sqrt{6}-\sqrt{2}}{4}$; $\dfrac{\sqrt{6}+\sqrt{2}}{4}$; $\dfrac{\sqrt{6}+\sqrt{2}}{4}$; $\dfrac{\sqrt{6}-\sqrt{2}}{4}$',
    r'''$\sin 15^{\circ}=\sin(45^{\circ}-30^{\circ})=\frac{\sqrt{6}-\sqrt{2}}{4}$, $\cos 15^{\circ}=\frac{\sqrt{6}+\sqrt{2}}{4}$,
$\sin 75^{\circ}=\cos 15^{\circ}$, $\cos 75^{\circ}=\sin 15^{\circ}$.
Ответ: $\dfrac{\sqrt{6}-\sqrt{2}}{4}$; $\dfrac{\sqrt{6}+\sqrt{2}}{4}$; $\dfrac{\sqrt{6}+\sqrt{2}}{4}$; $\dfrac{\sqrt{6}-\sqrt{2}}{4}$.''')
add(D, 6,
    r'$2-\sqrt{3}$',
    r'''$\operatorname{tg}15^{\circ}=\operatorname{tg}(45^{\circ}-30^{\circ})=\frac{1-1/\sqrt{3}}{1+1/\sqrt{3}}=2-\sqrt{3}$.
Ответ: $2-\sqrt{3}$.''')
add(D, 7,
    r'доказано',
    r'''Общий катет $1$. Против $\alpha$ и $\beta$ откладываем синусы, по прилежащим — косинусы.
Площадь большого прямоугольника / высота даёт $\sin(\alpha+\beta)=\sin\alpha\cos\beta+\cos\alpha\sin\beta$.
Ответ: доказано.''')
add(D, 8,
    r'$3\sqrt{10}$',
    r'''Стороны $n-1$, $n$, $n+1$, средний угол против $n$, $\cos=\frac23$.
$n^{2}=(n-1)^{2}+(n+1)^{2}-\frac43(n^{2}-1)$, $n^{2}=10$, периметр $3\sqrt{10}$.
Ответ: $3\sqrt{10}$.''')
add(D, 9,
    r'б, в',
    r'''а) пропорциональны синусам. б) верно. в) верно. г) $S=\frac{abc}{4R}$.
Ответ: б, в.''')
add(D, 10,
    r'$-\dfrac{1}{2}$',
    r'''$-\frac12-32\cdot\frac{1}{16}+0-2\cdot(-1)=-\frac12-2+2=-\frac12$.
Ответ: $-\dfrac{1}{2}$.''')
add(D, 11,
    r'$\dfrac{2}{3}$; $\dfrac{\sqrt{69}}{2}$; $\dfrac{5\sqrt{5}}{2}$',
    r'''$\cos B=\frac{9+25-14}{30}=\frac23$. Медиана $CM=\frac12\sqrt{50+28-9}=\frac{\sqrt{69}}{2}$.
$\sin B=\frac{\sqrt{5}}{3}$, $S=\frac{5\sqrt{5}}{2}$.
Ответ: $\dfrac{2}{3}$; $\dfrac{\sqrt{69}}{2}$; $\dfrac{5\sqrt{5}}{2}$.''')
add(D, 12,
    r'$\dfrac{119}{169}$; $\dfrac{1785}{169}$',
    r'''$5{-}12{-}13$, $CH=\frac{60}{13}$, $CM=\frac{13}{2}$.
$\cos\angle HCM=\frac{120}{169}$, $\sin=\frac{119}{169}$, $S=\frac{1785}{169}$.
Ответ: $\dfrac{119}{169}$; $\dfrac{1785}{169}$.''')
add(D, 13,
    r'$\dfrac{\sqrt{3}-1}{4}$; $\dfrac{\sqrt{3}-1}{8}$; $\dfrac{\sqrt{3}+1}{4}$',
    r'''Углы $30^{\circ}$, $135^{\circ}$, $15^{\circ}$. Площади при стороне $1$:
против $30^{\circ}$: $\frac{\sqrt{3}-1}{4}$; против $135^{\circ}$: $\frac{\sqrt{3}-1}{8}$; против $15^{\circ}$: $\frac{\sqrt{3}+1}{4}$.
Ответ: $\dfrac{\sqrt{3}-1}{4}$; $\dfrac{\sqrt{3}-1}{8}$; $\dfrac{\sqrt{3}+1}{4}$.''')
add(D, 14,
    r'нет верных',
    r'''а) $25+64<100$ — тупоугольный. б) $S=5$, не $10$. в) только у остроугольного. г) неверная формула.
Ответ: нет верных.''')
add(D, 15,
    r'$2\sqrt{3}-4$',
    r'''$2\sqrt{3}-32\cdot\frac{1}{32}+0+3\cdot(-1)=2\sqrt{3}-1-3=2\sqrt{3}-4$.
Ответ: $2\sqrt{3}-4$.''')
add(D, 16,
    r'$\dfrac{1}{2}$; $\sqrt{7}$; $3\sqrt{3}$',
    r'''$\cos A=\frac{16+9-13}{24}=\frac12$. $CM=\frac12\sqrt{26+18-16}=\sqrt{7}$. $S=3\sqrt{3}$.
Ответ: $\dfrac{1}{2}$; $\sqrt{7}$; $3\sqrt{3}$.''')
add(D, 17,
    r'$10$; $\dfrac{24}{25}$; $\dfrac{336}{25}$',
    r'''$AB=20$, медиана $CK=10$, $CH=\frac{48}{5}$.
$\cos\angle CKH=\frac{24}{25}$, $S_{CKH}=\frac{336}{25}$.
Ответ: $10$; $\dfrac{24}{25}$; $\dfrac{336}{25}$.''')
add(D, 18,
    r'$\dfrac{3-\sqrt{3}}{8}$; $\dfrac{3-\sqrt{3}}{12}$; $\dfrac{3+\sqrt{3}}{4}$',
    r'''Углы $45^{\circ}$, $120^{\circ}$, $15^{\circ}$. Площади при стороне $1$:
против $45^{\circ}$: $\frac{3-\sqrt{3}}{8}$; против $120^{\circ}$: $\frac{3-\sqrt{3}}{12}$; против $15^{\circ}$: $\frac{3+\sqrt{3}}{4}$.
Ответ: $\dfrac{3-\sqrt{3}}{8}$; $\dfrac{3-\sqrt{3}}{12}$; $\dfrac{3+\sqrt{3}}{4}$.''')

D = '9 класс/КР 9 класс геометрия/matvert9-kr2-koord'
add(D, 1,
    r'$(10;2)$',
    r'''$C=B+D-A=(-1+9+2;\,4+1-3)=(10;2)$.
Ответ: $(10;2)$.''')
add(D, 2,
    r'$\dfrac{119}{169}$; $-\dfrac{5}{4}$; $-\dfrac{36}{5}$; $-15$',
    r'''а) $\dfrac{-50+288}{13\cdot 26}=\dfrac{119}{169}$.
б) $\frac{-5}{x}=\frac{12}{3}$, $x=-\frac54$.
в) $10x+72=0$, $x=-\frac{36}{5}$.
г) $\vec p-\vec q-\vec r=(-15-x;-15)$, минимум при $x=-15$.
Ответ: $\dfrac{119}{169}$; $-\dfrac{5}{4}$; $-\dfrac{36}{5}$; $-15$.''')
add(D, 3,
    r'$\dfrac{\sqrt{4273}}{6}$',
    r'''Середина $BC$ $\bigl(\frac{11}{2};5\bigr)$, точка $1:2$ на $AD$ $\bigl(-4;-\frac13\bigr)$.
Расстояние $\sqrt{\bigl(\frac{19}{2}\bigr)^{2}+\bigl(\frac{16}{3}\bigr)^{2}}=\dfrac{\sqrt{4273}}{6}$.
Ответ: $\dfrac{\sqrt{4273}}{6}$.''')
add(D, 4,
    r'$x+2y-5=0$; $y=-\frac12 x+\frac52$; $x+2y+4=0$, $F(0;-2)$; $2x-y=0$; $9$; $\dfrac{9\sqrt{5}}{5}$',
    r'''а) $x+2y-5=0$. б) $y=-\frac x2+\frac52$.
в) $x+2y+4=0$, например $F(0;-2)$. г) $y=2x$.
д) $S_{MNF}=9$. е) $\frac{9}{\sqrt{5}}=\frac{9\sqrt{5}}{5}$.
Ответ: $x+2y-5=0$; $y=-\frac12 x+\frac52$; $x+2y+4=0$, $F(0;-2)$; $2x-y=0$; $9$; $\dfrac{9\sqrt{5}}{5}$.''')
add(D, 6,
    r'$(2;4)$',
    r'''$Q=M+P-N=(1+3-2;\,-5+3+6)=(2;4)$.
Ответ: $(2;4)$.''')
add(D, 7,
    r'$\dfrac{16}{65}$; $-\dfrac{3}{4}$; $-\dfrac{5}{12}$; $9$',
    r'''а) $\frac{36-20}{5\cdot 13}=\frac{16}{65}$. б) $x=-\frac34$. в) $12x+5=0$, $x=-\frac{5}{12}$.
г) $(x-9;-8)$, минимум при $x=9$.
Ответ: $\dfrac{16}{65}$; $-\dfrac{3}{4}$; $-\dfrac{5}{12}$; $9$.''')
add(D, 8,
    r'$\dfrac{\sqrt{2474}}{4}$',
    r'''Середина $AB$ $(3;-4)$, точка $1:3$ на $CD$ $\bigl(-\frac{13}{4};\frac{27}{4}\bigr)$.
Расстояние $\dfrac{\sqrt{625+1849}}{4}=\dfrac{\sqrt{2474}}{4}$.
Ответ: $\dfrac{\sqrt{2474}}{4}$.''')
add(D, 9,
    r'$3x+y-4=0$; $y=-3x+4$; $3x+y-6=0$, $F(2;0)$; $x-3y=0$; $1$; $\dfrac{\sqrt{10}}{5}$',
    r'''а) $3x+y-4=0$. б) $y=-3x+4$. в) $3x+y-6=0$, $F(2;0)$. г) $y=\frac x3$.
д) $S=1$. е) $\frac{2}{\sqrt{10}}=\frac{\sqrt{10}}{5}$.
Ответ: $3x+y-4=0$; $y=-3x+4$; $3x+y-6=0$, $F(2;0)$; $x-3y=0$; $1$; $\dfrac{\sqrt{10}}{5}$.''')
add(D, 11,
    r'$(-3;6)$',
    r'''$Q=M+P-N=(3-4-2;\,-2+2+6)=(-3;6)$.
Ответ: $(-3;6)$.''')
add(D, 12,
    r'$-\dfrac{16}{65}$; $-\dfrac{3}{2}$; $-\dfrac{5}{6}$; $-15$',
    r'''а) $\frac{20-36}{5\cdot 13}=-\frac{16}{65}$. б) $x=-\frac32$. в) $10+12x=0$, $x=-\frac56$.
г) $(-3;-15-x)$, минимум при $x=-15$.
Ответ: $-\dfrac{16}{65}$; $-\dfrac{3}{2}$; $-\dfrac{5}{6}$; $-15$.''')
add(D, 13,
    r'$\dfrac{\sqrt{997}}{5}$',
    r'''Середина $AB$ $(-3;7)$, точка $2:3$ на $CD$ $\bigl(\frac{16}{5};\frac{41}{5}\bigr)$.
Расстояние $\dfrac{\sqrt{961+36}}{5}=\dfrac{\sqrt{997}}{5}$.
Ответ: $\dfrac{\sqrt{997}}{5}$.''')
add(D, 14,
    r'$2x+3y-5=0$; $y=-\frac23 x+\frac53$; $2x+3y+3=0$, $F(0;-1)$; $3x-2y=0$; $4$; $\dfrac{8\sqrt{13}}{13}$',
    r'''а) $2x+3y-5=0$. б) $y=-\frac23 x+\frac53$. в) $2x+3y+3=0$, $F(0;-1)$. г) $y=\frac32 x$.
д) $S=4$. е) $\frac{8}{\sqrt{13}}=\frac{8\sqrt{13}}{13}$.
Ответ: $2x+3y-5=0$; $y=-\frac23 x+\frac53$; $2x+3y+3=0$, $F(0;-1)$; $3x-2y=0$; $4$; $\dfrac{8\sqrt{13}}{13}$.''')


if __name__ == '__main__':
    apply_solutions(I)
