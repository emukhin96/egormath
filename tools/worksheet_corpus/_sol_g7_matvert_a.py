# noqa: E501
import sys
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from worksheet_corpus._apply_agent_solutions import apply_solutions

I = []


def add(did, i, answer, solution, warning=''):
    I.append({'id': did, 'i': i, 'answer': answer, 'solution': solution,
              'warning': warning})


def flush(label):
    global I
    print('====', label, '====')
    apply_solutions(I)
    I = []


# ----- matvert-kr1 -----
D = '7 класс/matvert-kr1'
add(D, 1, r'пересекаются',
    r'В $\triangle ACK$ отрезок $AB$ — медиана (т.к. $B$ — середина $CK$), отрезок $KM$ — медиана (т.к. $M$ — середина $AC$). Медианы пересекаются в центроиде, поэтому прямые $AB$ и $KM$ пересекаются.')
add(D, 2, r'$14$ см',
    r'Пусть $A=0$, $B=28$, $C=c$. Середины $AC$ и $CB$ имеют координаты $c/2$ и $(c+28)/2$. Расстояние $\bigl|(c+28)/2-c/2\bigr|=14$ не зависит от $C$.')
add(D, 3, r'два варианта: луч $OE$ по разные стороны от $OB$, $\angle BOE=\angle AOC$',
    r'От луча $OB$ откладываем угол, равный $\angle AOC$. Это можно сделать по две стороны от $OB$, поэтому есть два положения луча $OE$.')
add(D, 4, r'$90^{\circ}$',
    r'Пусть $\angle COD=\gamma$, $\angle AOB=\alpha$ и $\gamma+\alpha=180^{\circ}$. Тогда $\angle COA+\angle BOD=\gamma-\alpha$. Угол между биссектрисами $\angle EOF=\frac12(\angle COA+\angle BOD)+\alpha=\frac{\gamma+\alpha}{2}=90^{\circ}$.')
add(D, 6, r'пересекаются (в точке $A$)',
    r'Точка $A$ — середина $KH$, поэтому $A\in KH$. Прямая $AP$ проходит через $A$, значит $AP$ и $KH$ пересекаются в $A$.')
add(D, 7, r'$54$ см',
    r'$CD=88-24-44=20$. Середина $AC$ отстоит от $A$ на $12$, середина $DB$ — на $24+20+22=66$. Расстояние $66-12=54$, или $\frac{AC}{2}+CD+\frac{DB}{2}=12+20+22=54$.')
add(D, 8, r'два варианта: луч $OD$ по разные стороны от $OA$ (или от подходящего луча), $\angle AOD=\angle COB$',
    r'От луча $OA$ откладываем угол, равный $\angle COB$. Два положения луча $OD$: по разные стороны от $OA$. Возможен также вариант, когда $OD$ лежит в $\angle AOB$ так, что $\angle AOD=\angle COB$.')
add(D, 9, r'$120^{\circ}$',
    r'$\angle AOC+\angle BOD=140^{\circ}-100^{\circ}=40^{\circ}$. Угол между биссектрисами равен $\frac12(\angle AOC+\angle BOD)+\angle AOB=20^{\circ}+100^{\circ}=120^{\circ}$, или $\frac{140^{\circ}+100^{\circ}}{2}=120^{\circ}$.')
flush(D)

# ----- matvert-kr3 -----
D = '7 класс/matvert-kr3'
add(D, 1, r'$75^{\circ}$ и $105^{\circ}$',
    r'$AB\parallel CD$, секущая $MN$. Углы $AMN$ и $CNM$ — односторонние внутренние, сумма $180^{\circ}$. Если $\angle AMN=\angle CNM+30^{\circ}$, то $\angle CNM=75^{\circ}$, $\angle AMN=105^{\circ}$. Остальные неразвёрнутые — вертикальные или смежные с ними: $75^{\circ}$ и $105^{\circ}$.')
add(D, 2, r'$37^{\circ}$, $37^{\circ}$, $106^{\circ}$',
    r'$DM$ — биссектриса $\angle CDE=74^{\circ}$, поэтому $\angle MDN=37^{\circ}$. В $\triangle DMN$ дано $DN=MN$, значит он равнобедренный: $\angle DMN=\angle MDN=37^{\circ}$, $\angle DNM=106^{\circ}$.')
add(D, 3, r'$\angle 3=36^{\circ}$, $\angle 4=144^{\circ}$',
    r'Из $\angle 1=\angle 2$ прямые параллельны (накрест лежащие или соответственные). Тогда $\angle 3$ и $\angle 4$ смежные при прямой: $\angle 3+\angle 4=180^{\circ}$ и $\angle 4=4\angle 3$, откуда $5\angle 3=180^{\circ}$, $\angle 3=36^{\circ}$, $\angle 4=144^{\circ}$.',
    'Рисунок к задаче в корпусе отсутствует; взята стандартная конфигурация односторонних/смежных углов.')
add(D, 4, r'$63^{\circ}$; $AB$ и $CD$ пересекаются',
    r'$AC\perp$ прямой и $BD\perp$ той же прямой, поэтому $AC\parallel BD$. При секущей $AB$ односторонние внутренние: $\angle BAC+\angle ABD=180^{\circ}$, $\angle ABD=63^{\circ}$. Если бы $AB\parallel CD$, то $AB$ была бы параллельна данной прямой и $\angle BAC=90^{\circ}$, что противоречит $117^{\circ}$. Значит $AB$ и $CD$ пересекаются.')
add(D, 6, r'$45^{\circ}$ и $135^{\circ}$',
    r'Односторонние внутренние: $\angle AMN+\angle CNM=180^{\circ}$ и $\angle CNM=3\angle AMN$, откуда $\angle AMN=45^{\circ}$, $\angle CNM=135^{\circ}$. Все неразвёрнутые углы равны $45^{\circ}$ или $135^{\circ}$.')
add(D, 7, r'$32^{\circ}$, $32^{\circ}$, $116^{\circ}$',
    r'$AD$ — биссектриса $\angle BAC=64^{\circ}$, поэтому $\angle DAE=32^{\circ}$. В $\triangle AED$ дано $AE=ED$, значит $\angle ADE=\angle DAE=32^{\circ}$, $\angle AED=116^{\circ}$.')
add(D, 8, r'$\angle 3=55^{\circ}$, $\angle 4=125^{\circ}$',
    r'Из $\angle 1+\angle 2=180^{\circ}$ прямые параллельны. Тогда $\angle 3+\angle 4=180^{\circ}$ и $\angle 4-\angle 3=70^{\circ}$, откуда $\angle 4=125^{\circ}$, $\angle 3=55^{\circ}$.',
    'Рисунок к задаче в корпусе отсутствует.')
add(D, 9, r'$135^{\circ}$',
    r'$\angle BAC+\angle ABD=43^{\circ}+137^{\circ}=180^{\circ}$, при секущей $AB$ получаем $BD\parallel AC$. При секущей $DC$ односторонние внутренние: $\angle BDC+\angle ACD=180^{\circ}$, $\angle ACD=135^{\circ}$. Если $AB\parallel DC$, то $\angle ACD$ равнялся бы $43^{\circ}$ или $137^{\circ}$; это не так, значит прямые $AB$ и $DC$ пересекаются.')
flush(D)

# ----- matvert-self1 -----
D = '7 класс/matvert-self1'
add(D, 0, r'$33$ м',
    r'Из $5CD=4DB$ и $CD=12$ имеем $DB=15$, $CB=27=AC$. Середина $AC$ отстоит от $C$ на $13{,}5$, далее $CD=12$, от $D$ до середины $DB$ ещё $7{,}5$. Итого $13{,}5+12+7{,}5=33$.')
add(D, 1, r'$80^{\circ}$, $100^{\circ}$, $80^{\circ}$, $100^{\circ}$',
    r'Вертикальные углы равны, смежные дают $180^{\circ}$. Отношение $4:5$ возможно только у смежных: $4k+5k=180^{\circ}$, $k=20^{\circ}$. Углы $80^{\circ}$ и $100^{\circ}$.')
add(D, 2, r'$33$ м',
    r'То же, что в первом варианте: $DB=15$, $AC=CB=27$, расстояние между серединами $AC$ и $DB$ равно $33$.')
add(D, 3, r'$80^{\circ}$, $100^{\circ}$, $80^{\circ}$, $100^{\circ}$ или $60^{\circ}$, $120^{\circ}$, $60^{\circ}$, $120^{\circ}$',
    r'Пусть один угол равен $x$, смежный $180^{\circ}-x$. Если $x=60^{\circ}+\frac12(180^{\circ}-x)$, то $x=100^{\circ}$. Если сравнивают равные вертикальные: $x=60^{\circ}+\frac x2$, то $x=120^{\circ}$. Оба набора допустимы.')
flush(D)

# ----- matvert-self2 -----
D = '7 класс/matvert-self2'
add(D, 0, r'$\dfrac{14\sqrt{93}}{17}$ см',
    r'Гипотенуза $CE$ и катет $CD$: сумма $31$, разность $3$, поэтому $CE=17$, $CD=14$. Второй катет $DE=\sqrt{17^2-14^2}=\sqrt{93}$. Расстояние от $C$ до $DE$ — высота к гипотенузе: $\frac{CD\cdot DE}{CE}=\frac{14\sqrt{93}}{17}$.')
add(D, 1, r'доказано',
    r'В равнобедренном $\triangle ABC$ ($AB=CB$) ось симметрии — высота/медиана из вершины на основание. Середина основания лежит на оси симметрии, поэтому равноудалена от боковых сторон.')
add(D, 2, r'$3$ см',
    r'$AB\parallel CD$, $AD$ — наклонная, $\angle ADC=30^{\circ}$. Расстояние между параллельными равно $AD\sin 30^{\circ}=6\cdot\frac12=3$.')
add(D, 3, r'доказано',
    r'Пусть точки $A$ и $B$ лежат по одну сторону от прямой $\ell$ и $AA_1=BB_1=h$, где $A_1$, $B_1$ — основания перпендикуляров. Тогда $AA_1\parallel BB_1$ и $AA_1=BB_1$, четырёхугольник $AA_1B_1B$ — прямоугольник, откуда $AB\parallel \ell$. Любая такая точка лежит на этой прямой.')
add(D, 4, r'доказано',
    r'Прямые $b\parallel c$. Точки $A$, $C$, $B$ лежат на одной прямой, $C$ — середина $AB$. Расстояния до семейства параллельных меняются линейно вдоль $AB$, поэтому шаг $A\to c$ равен шагу $C\to b$, а расстояние от $A$ до $b$ вдвое больше расстояния между $b$ и $c$.')
flush(D)

# ----- matvert-task-sample -----
D = '7 класс/matvert-task-sample'
add(D, 0, r'$90^{\circ}=\angle DOA+\angle AOC$',
    r'По условию $DO\perp OC$, поэтому $\angle DOC=90^{\circ}$. Луч $OA$ лежит внутри $\angle DOC$, значит $\angle DOC=\angle DOA+\angle AOC$.')
add(D, 1, r'$90^{\circ}-\alpha$',
    r'$\angle AOC=\angle DOC-\angle DOA=90^{\circ}-\alpha$.')
add(D, 2, r'$90^{\circ}-\alpha$',
    r'$OC$ — биссектриса $\angle AOB$, поэтому $\angle COB=\angle AOC=90^{\circ}-\alpha$.')
add(D, 3, r'$\angle AOB=\angle AOC+\angle COB$',
    r'Луч $OC$ лежит внутри $\angle AOB$, поэтому $\angle AOB=\angle AOC+\angle COB$.')
add(D, 4, r'$180^{\circ}-2\alpha$',
    r'$\angle AOB=(90^{\circ}-\alpha)+(90^{\circ}-\alpha)=180^{\circ}-2\alpha$.')
flush(D)

# ----- matvert-test1-v1 -----
D = '7 класс/matvert-test1-v1'
add(D, 0, r'пересекаются',
    r'В $\triangle ACK$ прямые $AB$ и $KM$ — медианы, они пересекаются.')
add(D, 1, r'$2:3$',
    r'Точки идут в порядке $A,C,D,T,H,F,B$, шесть равных частей. $AD=2$ части, $TB=3$ части, отношение $2:3$.')
add(D, 2, r'$28\dfrac{4}{7}$',
    r'$BC=57\dfrac{3}{7}=\dfrac{400}{7}$, точка $A$ — середина, $AB=\dfrac{200}{7}=28\dfrac{4}{7}$.')
add(D, 3, r'$125\%$',
    r'Пусть $BC=2$, тогда $BA=AC=1$, $AM=MC=\frac12$. Так как $C$ — середина $KM$, точка $K$ лежит за $C$ и $CK=\frac12$. Тогда $BK=2{,}5$, $\frac{BK}{BC}=\frac{5}{4}=125\%$.')
add(D, 4, r'$8$ см',
    r'$M$ лежит на $AB$ и $BA$, значит на отрезке $AB$, и $MA=MB$, поэтому $M$ — середина. $MB=\frac12 AB$ и $MB=AB-8$, откуда $AB=16$, $MB=8$.')
add(D, 5, r'$27{,}3$ м',
    r'$AP=0{,}3\cdot 91=27{,}3$.')
add(D, 6, r'$15$',
    r'По рисунку $A{-}C{-}B{-}D$, общая часть длины $3$. Тогда $AD=AB+CD-3=7+11-3=15$.')
add(D, 7, r'$6$',
    r'Четыре точки на прямой: число отрезков $\binom{4}{2}=6$.')
add(D, 8, r'$45$',
    r'Порядок $A{-}B{-}C{-}D$: $AB=7$, $BC=3$, $CD=4$, $AC=10$, $AD=14$, $BD=7$. Сумма $45$.')
add(D, 9, r'$7$; бонус: $3$',
    r'Середина $AC$ на расстоянии $5$ от $A$ ($AC=10$), середина $CD$ — на расстоянии $12$; разность $7$. Бонус: при $K=0$, $T=\pm 11$ наименьшее $EM$ равно $3$.')
flush(D)

# ----- matvert-test1-v2 -----
D = '7 класс/matvert-test1-v2'
add(D, 0, r'пересекаются (в точке $A$)',
    r'$A$ — середина $KH$, поэтому прямые $AP$ и $KH$ пересекаются в $A$.')
add(D, 1, r'$5:3$',
    r'Порядок $A,C,D,T,H,F,B$. $BC=5$ частей, $DF=3$ части, отношение $5:3$.')
add(D, 2, r'$42\dfrac{6}{7}$',
    r'$PC=14\dfrac{2}{7}=\dfrac{100}{7}$. $P$ — середина $KC$, поэтому $KC=\dfrac{200}{7}$. $K$ — середина $BC$, $BC=\dfrac{400}{7}$. Тогда $BP=BK+KP=\dfrac{200}{7}+\dfrac{100}{7}=\dfrac{300}{7}=42\dfrac{6}{7}$.')
add(D, 3, r'$12{,}5\%$',
    r'Пусть $AC=CB=1$, $AB=2$. Тогда $CM=\frac12$. $B$ — середина $AK$, поэтому $AK=4$. $\frac{CM}{AK}=\frac{1}{8}=12{,}5\%$.')
add(D, 4, r'$18$ см',
    r'$B$ на отрезке $MK$ и $MB:MK=2:3$, поэтому $MB=\frac23 MK$. По условию $MK=MB+6$, откуда $\frac13 MK=6$, $MK=18$.')
add(D, 5, r'$33{,}6$ м',
    r'$AP=0{,}4\cdot 84=33{,}6$.')
add(D, 6, r'$26$',
    r'$AD=AB+CD-7=16+17-7=26$.')
add(D, 7, r'$6$',
    r'Через каждые две из четырёх точек, никакие три не коллинеарны: $\binom{4}{2}=6$ прямых.')
add(D, 8, r'$74$',
    r'Порядок $A{-}B{-}C{-}D$: $AB=11$, $BC=5$, $CD=7$, $AC=16$, $AD=23$, $BD=12$. Сумма $74$.')
add(D, 9, r'$11{,}5$; бонус: $5$',
    r'$AC=16$, середина на расстоянии $8$ от $A$; середина $CD$ на расстоянии $19{,}5$; разность $11{,}5$. Бонус: при $AC=34$, $AK=15$, $BC=14$ наименьшее $BK$ равно $5$.')
flush(D)

# ----- matvert7-test5-summa -----
D = '7 класс/matvert7-test5-summa'
add(D, 0, r'$51^{\circ}$',
    r'Третий угол $180^{\circ}-27^{\circ}-75^{\circ}=78^{\circ}$. Больший $78^{\circ}$, меньший $27^{\circ}$, разность $51^{\circ}$.')
add(D, 1, r'$80^{\circ}$',
    r'Прямые $AM$ и $BD$ пересекаются в $C$, поэтому $\angle ACB$ и $\angle MCD$ вертикальны и равны. $\angle CBA+\angle CAB=180^{\circ}-\angle ACB$, $\angle CMD+\angle CDM=180^{\circ}-\angle MCD$. Сумма четырёх углов $360^{\circ}-2\angle MCD=200^{\circ}$, откуда $\angle MCD=80^{\circ}$.')
add(D, 2, r'$44\%$',
    r'Больший угол $125^{\circ}$, сумма двух меньших $55^{\circ}$. $\frac{55}{125}\cdot 100\%=44\%$.')
add(D, 3, r'$30^{\circ}$',
    r'$2+3+7=12$ частей, $180^{\circ}/12=15^{\circ}$, меньший угол $2\cdot 15^{\circ}=30^{\circ}$.')
flush(D)
