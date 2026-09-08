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


def flush(did):
    rows = [x for x in I if x['id'] == did]
    if rows:
        apply_solutions(rows)


# ---------- тесты многоугольники ----------
def mnogoug_pack(did, n0, opp, small_or_large, pct, n_eq, n_mid, n_star, *,
                 other_is_smaller=False, find_larger=True):
    """n0: n-gon diagonals from one vertex → n-2 triangles.
    opp: sum of two opposite angles.
    small_or_large: the given of the other pair.
    """
    add(did, 0, f'${n0 - 2}$',
        rf'Из одной вершины $n$-угольника ($n={n0}$) диагонали делят его на $n-2={n0-2}$ треугольника.')
    rest = 360 - opp
    if find_larger:
        ans = rest - small_or_large
        add(did, 1, rf'${ans}^\circ$',
            rf'Сумма двух оставшихся углов $360^\circ-{opp}^\circ={rest}^\circ$. '
            rf'Меньший из них ${small_or_large}^\circ$, больший ${ans}^\circ$.')
    else:
        ans = rest - small_or_large
        add(did, 1, rf'${ans}^\circ$',
            rf'Сумма двух оставшихся углов $360^\circ-{opp}^\circ={rest}^\circ$. '
            rf'Больший из них ${small_or_large}^\circ$, меньший ${ans}^\circ$.')
    # x = p/100 * (360-x)
    p = pct
    x = 360 * p / (100 + p)
    add(did, 2, rf'${int(x) if x==int(x) else x}^\circ$',
        rf'Пусть угол равен $x$, тогда $x=\dfrac{{{p}}}{{100}}(360^\circ-x)$, '
        rf'$x=\dfrac{{{int(x) if x==int(x) else x}}}^\circ$.')
    each = (n_eq - 2) * 180 // n_eq
    add(did, 3, rf'${each}^\circ$',
        rf'Сумма углов $({n_eq}-2)\cdot 180^\circ={(n_eq-2)*180}^\circ$, каждый $\dfrac{{{(n_eq-2)*180}}}{{{n_eq}}}={each}^\circ$.')
    smid = (n_mid - 2) * 180
    add(did, 4, rf'${smid}^\circ$',
        rf'Середины соседних сторон $n$-угольника снова дают $n$-угольник, сумма углов $({n_mid}-2)\cdot 180^\circ={smid}^\circ$.')
    add(did, 5, rf'${n_star * 180}^\circ$',
        rf'Получается ${n_star}$ треугольников, сумма их углов ${n_star}\cdot 180^\circ={n_star*180}^\circ$.')


for D in ('8 класс/8m-test1-mnogoug', '8 класс/8m-test1-mnogoug-v1'):
    mnogoug_pack(D, 9, 160, 60, 80, 6, 7, 10, find_larger=True)
    flush(D)

mnogoug_pack('8 класс/8m-test1-mnogoug-v2', 8, 100, 110, 60, 8, 10, 11)
flush('8 класс/8m-test1-mnogoug-v2')

mnogoug_pack('8 класс/8m-test1-mnogoug-v3', 10, 260, 60, 25, 10, 9, 9, find_larger=False)
flush('8 класс/8m-test1-mnogoug-v3')

mnogoug_pack('8 класс/8m-test1-mnogoug-v4', 11, 100, 165, 20, 12, 8, 8, find_larger=False)
flush('8 класс/8m-test1-mnogoug-v4')

# ---------- test3 parall trap ----------
D = '8 класс/matvert8-test3-parall_trap'
add(D, 0, r'$4$',
    r'В прямоугольнике $KMPT$ треугольник $TKP$ прямоугольный с гипотенузой $KP=8$. Медиана к гипотенузе равна её половине: $4$.')
add(D, 1, r'$120^\circ$',
    r'Сторона $a$ равна диагонали. Половинки диагоналей $a/2$ и $a\sqrt{3}/2$ дают углы $30^\circ$ и $60^\circ$, углы ромба $60^\circ$ и $120^\circ$. Больший $120^\circ$.')
add(D, 2, r'$40^\circ$',
    r'Угол $90^\circ$ делится в отношении $2:7$ на $20^\circ$ и $70^\circ$. Угол между диагоналями равен $2\cdot 20^\circ=40^\circ$.')
add(D, 3, r'$90^\circ$',
    r'Биссектриса $AK$ отсекает равнобедренный $\triangle ABK$ ($AB=BK$). Прямая $PK\parallel AB$ пересекает $AD$ в $P$. Векторы $\overrightarrow{AK}$ и $\overrightarrow{PB}$ ортогональны, угол $90^\circ$.')
add(D, 4, r'$15$',
    r'Центр ромба равноудалён от противоположных сторон, поэтому высота равна удвоенному расстоянию $2\cdot 7{,}5=15$. Все высоты ромба равны.')
flush(D)

# ---------- test4 fales ----------
D = '8 класс/matvert8-test4-fales_srlin_trap'
add(D, 0, r'$10{,}8$',
    r'Средняя линия $m=a/2$ и $m=a-3{,}6$, откуда $a=7{,}2$, $m=3{,}6$, сумма $10{,}8$.')
add(D, 1, r'$21$',
    r'$\angle D=120^\circ$, $BD=AD=BC$, поэтому $\triangle BCD$ равносторонний, все стороны параллелограмма равны $14$. $M$, $N$ — середины, $\triangle CMN$ равносторонний со стороной $7$, периметр $21$.')
add(D, 2, r'$4$',
    r'Разность оснований $8$, свес по $4$. Угол при большем основании $45^\circ$, высота $4$.')
add(D, 3, r'$2{,}5$',
    r'Отрезок между точками пересечения диагоналей со средней линией равен половине разности оснований: $(23-18)/2=2{,}5$.')
add(D, 4, r'$15$; $120^\circ$; $\dfrac{50}{3}$',
    r'''$AB$ на $1/3$ высоты от меньшего основания: $12+(21-12)/3=15$.
Три стороны по $4$, основание $8$: равнобедренная трапеция, свес $2$, $\cos=1/2$, угол при большем основании $60^\circ$, больший угол $120^\circ$.
По теореме Фалеса на второй прямой пять равных отрезков; $BB_4-B_2B_3=3$ части $=10$, $OB_4=5\cdot\frac{10}{3}=\frac{50}{3}$.''')
add(D, 5, r'$16{,}2$',
    r'$m=a/2=a-5{,}4$, $a=10{,}8$, $m=5{,}4$, сумма $16{,}2$.')
add(D, 6, r'$13{,}5$',
    r'$\angle A=120^\circ$, $AC=CD=AB$, $\triangle ABC$ равносторонний, стороны по $9$. $K$, $M$ — середины, $\triangle KBM$ со стороной $4{,}5$, периметр $13{,}5$.')
add(D, 7, r'$6$',
    r'Разность оснований $12$, свес по $6$. Угол при большем основании $45^\circ$, высота $6$.')
add(D, 8, r'$3{,}5$; $21$; $40$; $\dfrac{70}{3}$',
    r'''$OA=(26-19)/2=3{,}5$.
$EK$ на $1/3$ от меньшего основания: $17+(29-17)/3=21$.
Равнобедренная трапеция, меньшее основание и боковые по $8$, угол $120^\circ$ при меньшем, большее основание $16$, периметр $40$.
Пять равных отрезков, $KK_4-K_1K_2=3$ части $=14$, $EK_4=5\cdot\frac{14}{3}=\frac{70}{3}$.''')
flush(D)

# ---------- test7 pifag ----------
D = '8 класс/matvert8-test7-pifag'


def sq_cut(did, i, side, a_leg, b_other):
    # four corner right triangles legs (ak, ap) etc. Pattern: two legs a and side-a
    area = side * side - 4 * (a_leg * (side - a_leg) / 2)
    add(did, i, f'${int(area) if area==int(area) else area}$',
        rf'Сторона квадрата ${side}$. Четыре угловых прямоугольных треугольника с катетами ${a_leg}$ и ${side-a_leg}$, площадь каждого ${a_leg*(side-a_leg)/2}$. '
        rf'$S={side**2}-4\cdot {a_leg*(side-a_leg)/2}={int(area) if area==int(area) else area}$.')


sq_cut(D, 0, 8, 3, 5)
add(D, 1, r'$4$',
    r'$(\sqrt{7}-1)^2+(\sqrt{7}+1)^2=16$, гипотенуза $4$.')
add(D, 2, r'$0$',
    r'Второй катет $\sqrt{41^2-40^2}=9$, периметр $90$, $90:5$ даёт остаток $0$.')
add(D, 3, r'$4+\sqrt{7}$',
    r'$K$ между $A$ и $C$: $AK=\sqrt{25-9}=4$, $CK=\sqrt{16-9}=\sqrt{7}$, $AC=4+\sqrt{7}$.')
add(D, 4, r'$4-\sqrt{7}$',
    r'$K$ вне отрезка $AC$: $AK=4$, $CK=\sqrt{7}$, $AC=4-\sqrt{7}$.')
add(D, 5, r'$2$',
    r'Медиана к гипотенузе равна её половине, гипотенуза $3$, второй катет $\sqrt{9-5}=2$.')
sq_cut(D, 6, 9, 4, 5)
add(D, 7, r'$4\sqrt{2}$',
    r'$(2\sqrt{3}-2)^2+(2\sqrt{3}+2)^2=32$, гипотенуза $4\sqrt{2}$.')
add(D, 8, r'$0$',
    r'Второй катет $\sqrt{181^2-180^2}=19$, периметр $380$, $380:19$ даёт остаток $0$.')
add(D, 9, r'$8+2\sqrt{7}$',
    r'$AK=\sqrt{64-36}=2\sqrt{7}$, $CK=8$, $AC=8+2\sqrt{7}$.')
add(D, 10, r'$8-2\sqrt{7}$',
    r'$K$ вне $AC$: $AK=8$, $CK=2\sqrt{7}$, $AC=8-2\sqrt{7}$.')
add(D, 11, r'$4$',
    r'Гипотенуза $5$, второй катет $4$.')
sq_cut(D, 12, 10, 3, 7)
add(D, 13, r'$2\sqrt{2}$',
    r'$(\sqrt{3}-1)^2+(\sqrt{3}+1)^2=8$, гипотенуза $2\sqrt{2}$.')
add(D, 14, r'$0$',
    r'Второй катет $17$, периметр $306$, $306:6$ даёт остаток $0$.')
add(D, 15, r'$8+3\sqrt{5}$',
    r'$AH=\sqrt{81-36}=3\sqrt{5}$, $CH=8$, $AC=8+3\sqrt{5}$.')
add(D, 16, r'$8-3\sqrt{5}$',
    r'$H$ вне $AC$: $AH=8$, $CH=3\sqrt{5}$, $AC=8-3\sqrt{5}$.')
add(D, 17, r'$3$',
    r'Гипотенуза $4$, второй катет $\sqrt{16-7}=3$.')
sq_cut(D, 18, 7, 5, 2)
add(D, 19, r'$2\sqrt{5}$',
    r'$(\sqrt{6}-2)^2+(\sqrt{6}+2)^2=20$, гипотенуза $2\sqrt{5}$.')
add(D, 20, r'$0$',
    r'Второй катет $13$, периметр $182$, $182:7$ даёт остаток $0$.')
add(D, 21, r'$3+4\sqrt{3}$',
    r'$AM=3$, $CM=\sqrt{64-16}=4\sqrt{3}$, $AC=3+4\sqrt{3}$.')
add(D, 22, r'$4\sqrt{3}-3$',
    r'$M$ вне $AC$: $AM=4\sqrt{3}$, $CM=3$, $AC=4\sqrt{3}-3$.')
add(D, 23, r'$5$',
    r'Гипотенуза $6$, второй катет $\sqrt{36-11}=5$.')
flush(D)

# ---------- test8 podob ----------
D = '8 класс/matvert8-test8-podob'
add(D, 0, r'$21$',
    r'Равносторонние треугольники подобны с коэффициентом $7/4$. Медианы в том же отношении: $BB_1=12\cdot 7/4=21$.')
add(D, 1, r'$51^\circ$',
    r'$\angle B=\angle B_1=66^\circ$, $\angle C=180^\circ-63^\circ-66^\circ=51^\circ$. Меньший угол $51^\circ$.')
add(D, 2, r'$3:1$',
    r'$A_1B_1\parallel AB$, $\triangle CA_1B_1\sim\triangle CAB$ с $k=1/4$. Тогда $A_1C:CA=1:4$, $A_1A:A_1C=3:1$.')
add(D, 3, r'$10$',
    r'Точка $K$ — центр подобия, $AB/CD=2/7$, $AB=35\cdot 2/7=10$.')
add(D, 4, r'$3$',
    r'По теореме Стюарта $12^2\cdot CK+6^2\cdot AK=12(6^2+AK\cdot CK)$. При $AK=12-CK$ получаем $CK=3$.')
add(D, 5, r'$8$',
    r'$KK_1=14\cdot 4/7=8$.')
add(D, 6, r'$70^\circ$',
    r'$\angle A=180^\circ-47^\circ-63^\circ=70^\circ$. Больший угол подобного треугольника $70^\circ$.')
add(D, 7, r'$3:2$',
    r'$A_1C_1\parallel AC$, коэффициент $1/2{,}5=2/5$. Тогда $A_1A:A_1C=3:2$.',
    'Отношение по подобию от вершины $B$; уточнить по рисунку, если $A_1$ иначе.')
add(D, 8, r'$25$',
    r'$AB/CD=5/3$, $AB=15\cdot 5/3=25$.')
add(D, 9, r'$3{,}5$',
    r'Аналогично задаче с сторонами $14$ и $7$: $CK=3{,}5$.')
add(D, 10, r'$24$',
    r'$AA_1=15\cdot 8/5=24$.')
add(D, 11, r'$44^\circ$',
    r'$\angle C=180^\circ-57^\circ-44^\circ=79^\circ$. Меньший угол $44^\circ$.')
add(D, 12, r'$2:1$',
    r'$CB_1:CB=1:3$, $B_1B:CB_1=2:1$.')
add(D, 13, r'$15$',
    r'$CD/AB=5/3$, $CD=9\cdot 5/3=15$.')
add(D, 14, r'$2{,}5$',
    r'По аналогии с $AB=AC=10$, $BC=5$, $BM=5$: $MC=2{,}5$.',
    'В условии повторяется $AC=5$; взято $BC=5$, $M$ на $AC$.')
flush(D)

# ---------- parallelogram tests (не пустой шаблон) ----------
def para_count(h, s):
    from math import comb
    return comb(h, 2) * comb(s, 2)


def flush_para(did, n_par, pct, semi, three_sum, ask, must_can, peri, ddiff, dwhat):
    add(did, 0, f'${n_par}$',
        rf'Параллелограмм задаётся выбором двух из горизонталей и двух из наклонных: на рисунке их ${n_par}$.')
    big = semi / (1 + pct / 100)
    small = semi - big
    add(did, 1, rf'${int(small) if small==int(small) else small}$ см',
        rf'Полупериметр ${semi}={a}+{pct/100:.2g}{a}$, меньшая сторона ${int(small) if small==int(small) else small}$ см.'.replace('{a}', 'a'))
    missing = 360 - three_sum
    if ask == 'obtuse':
        obt = missing if missing > 90 else 180 - missing
        add(did, 2, rf'${obt}^\circ$',
            rf'Четвёртый угол ${missing}^\circ$. Тупой угол параллелограмма ${obt}^\circ$.')
    else:
        ac = missing if missing < 90 else 180 - missing
        add(did, 3 and 2, rf'${ac}^\circ$',
            rf'Четвёртый угол ${missing}^\circ$. Острый угол ${ac}^\circ$.')
    add(did, 3, must_can,
        r'Условие даёт трапецию или вписанный четырёхугольник, но не обязательный параллелограмм: может, не должен.')
    add(did, 4, f'${peri // 2 - 1}$ см',
        rf'Стороны $a+b={peri//2}$, диагональ $<a+b$, наибольшее целое ${peri//2-1}$.')
    add(did, 5, f'${ddiff}$',
        rf'Разность периметров треугольников с общей половиной диагоналей равна разности сторон; {dwhat} ${ddiff}$.')


# fix the add(did, 3 and 2) bug - I'll write these manually

D = '8 класс/8-test2-parallelogramm-0v'
add(D, 0, r'$9$', r'Три прямые одного направления и три другого: $\binom{3}{2}\binom{3}{2}=9$.')
add(D, 1, r'$8$ см', r'$a+0{,}8a=18$, $a=10$, меньшая сторона $8$ см.')
add(D, 2, r'$120^\circ$', r'Четвёртый угол $60^\circ$, тупой $120^\circ$.')
add(D, 3, r'может, но не должен',
    r'Любые два неравных угла по $180^\circ$ — у параллелограмма и у равнобедренной трапеции. Может, не должен.')
add(D, 4, r'$9$ см', r'$a+b=10$, диагональ $<10$, наибольшее целое $9$.')
add(D, 5, r'$6$', r'$P_{OBC}-P_{AOB}=BC-AB=6$, то же $AD-DC=6$.')
flush(D)

D = '8 класс/8-test2-parallelogramm-VAR1'
add(D, 0, r'$9$', r'Три и три направления: $9$ параллелограммов.')
add(D, 1, r'$8$ см', r'$a+0{,}8a=18$, меньшая $8$ см.')
add(D, 2, r'$120^\circ$', r'Четвёртый угол $60^\circ$, тупой $120^\circ$.')
add(D, 3, r'может, но не должен',
    r'Условие выполнено у параллелограмма и у равнобедренной трапеции.')
add(D, 4, r'$9$ см', r'Диагональ $<10$, наибольшее целое $9$.')
add(D, 5, r'$6$', r'$BC-AB=6=AD-DC$.')
flush(D)

D = '8 класс/8-test2-parallelogramm-VAR2'
add(D, 0, r'$6$', r'Четыре прямые одного направления и две другого: $\binom{4}{2}\binom{2}{2}=6$.')
add(D, 1, r'$6$ см', r'$a+0{,}6a=16$, меньшая $6$ см.')
add(D, 2, r'$110^\circ$', r'Четвёртый угол $110^\circ$ — тупой.')
add(D, 3, r'может, но не должен',
    r'Два соседних угла по $180^\circ$ задают трапецию, не обязательно параллелограмм.')
add(D, 4, r'$14$ см', r'$a+b=15$, наибольшая целая диагональ $14$.')
add(D, 5, r'$8$', r'$P_{OBC}-P_{COD}=BC-CD=8$.')
flush(D)

D = '8 класс/8-test2-parallelogramm-v1'
add(D, 0, r'$6$', r'Четыре и две прямые: $6$ параллелограммов.')
add(D, 1, r'$6$ см', r'$a+0{,}6a=16$, меньшая $6$ см.')
add(D, 2, r'$110^\circ$', r'Четвёртый угол $110^\circ$.')
add(D, 3, r'может, но не должен',
    r'Только одна пара соседних углов по $180^\circ$ — признак трапеции, не параллелограмма.')
add(D, 4, r'$14$ см', r'$a+b=15$, наибольшее целое $14$.')
add(D, 5, r'$8$', r'$BC-CD=8$.')
flush(D)

D = '8 класс/8-test2-parallelogramm-VAR3'
add(D, 0, r'$10$', r'Две прямые одного направления и пять другого: $\binom{2}{2}\binom{5}{2}=10$.')
add(D, 1, r'$14$ см', r'$a+0{,}7a=34$, меньшая $14$ см.')
add(D, 2, r'$80^\circ$', r'Четвёртый угол $100^\circ$, острый $80^\circ$.')
add(D, 3, r'может, но не должен',
    r'Сумма противоположных $180^\circ$ — вписанный четырёхугольник, не обязательно параллелограмм.')
add(D, 4, r'$16$ см', r'$a+b=17$, наибольшее целое $16$.')
add(D, 5, r'$5$', r'$P_{OBC}-P_{COD}=AD-AB=5$.')
flush(D)

D = '8 класс/8-test2-parallelogramm-VAR4'
add(D, 0, r'$10$', r'Пять и две прямые: $\binom{5}{2}\binom{2}{2}=10$.')
add(D, 1, r'$6$ см', r'$a+0{,}75a=14$, меньшая $6$ см.')
add(D, 2, r'$20^\circ$', r'Четвёртый угол $160^\circ$, острый $20^\circ$.')
add(D, 3, r'может, но не должен',
    r'Два соседних по $180^\circ$ — трапеция, не обязательно параллелограмм.')
add(D, 4, r'$18$ см', r'$a+b=19$, наибольшее целое $18$.')
add(D, 5, r'$7$', r'$P_{AOD}-P_{AOB}=BC-DC=7$.')
flush(D)

# ---------- ДЗ многоугольники ----------
PROOF_PENT = (
    r'Диагонали $BE=BD$. В $\triangle ABE$ и $\triangle CBD$ имеем $\angle ABE=\angle CBD$, '
    r'$\angle BEA=\angle BDC$ и $BE=BD$ (ASA). Значит $AB=CB$, $AE=CD$. '
    r'Периметры $AB+BD+DE+EA$ и $CB+BE+ED+DC$ совпадают.')
ANG_PENT = (
    r'Сумма углов пятиугольника $540^\circ$. Пусть первый угол $x$, тогда '
    r'$5x+100^\circ=540^\circ$, $x=88^\circ$. Углы $88^\circ$, $98^\circ$, $108^\circ$, $118^\circ$, $128^\circ$.')
SIDES_N = (
    r'$(n-2)180^\circ/n=\alpha$. а) $90^\circ$ $\Rightarrow n=4$; б) $60^\circ$ $\Rightarrow n=3$; '
    r'в) $120^\circ$ $\Rightarrow n=6$; г) $108^\circ$ $\Rightarrow n=5$.')

D = '8 класс/hw/8m-dz1-mnogoug'
for i in (1, 4, 7):
    add(D, i, r'доказано', PROOF_PENT)
for i in (2, 5, 8):
    add(D, i, r'$88^\circ$, $98^\circ$, $108^\circ$, $118^\circ$, $128^\circ$', ANG_PENT)
for i in (3, 6, 9):
    add(D, i, r'$4$; $3$; $6$; $5$', SIDES_N)
flush(D)

D = '8 класс/hw/8m-dz2-mnogoug'
diag25 = r'$n(n-3)/2=25$, $n^2-3n-50=0$, дискриминант $209$ не квадрат, целого $n$ нет. Не может.'
ang10 = (r'Если $k$ углов по $10^\circ$, остальные $<180^\circ$: $10k+(n-k)180>(n-2)180$, $k<36/17$. '
         r'Значит $k\le 2$. Два угла по $10^\circ$ возможны (например $10^\circ,10^\circ,160^\circ$).')
for i in (1, 4, 7, 10):
    add(D, i, r'нет', diag25)
for i in (2, 5, 8, 11):
    add(D, i, r'не более двух', ang10)
flush(D)

# ---------- analysis vysk ----------
D = '8 класс/matvert8-analysis-vysk'
add(D, 0, r'$2$, $3$',
    r'1) ложно: квадрат — частный случай прямоугольника. 2) верно (признак равнобедренного). 3) верно.')
add(D, 1, r'$2$',
    r'1) ложно (параллельные не пересекаются). 2) верно. 3) ложно: только высота к основанию.')
add(D, 2, r'$1$, $3$',
    r'1) верно (равные соответственные). 2) ложно. 3) верно (бесконечно много прямых). 4) ложно.')
add(D, 3, r'$3$',
    r'1) и 2) верны, 4) верно ($360^\circ-200^\circ=160^\circ$). 3) ложно: смежные углы параллелограмма в сумме $180^\circ$.')
add(D, 4, r'$1$, $3$',
    r'1) верно (медиана/биссектриса/высота к основанию). 2) ложно. 3) верно.')
add(D, 5, r'$2$, $3$',
    r'1) ложно (смежный тупой). 2) верно. 3) верно.')
add(D, 6, r'$2$, $3$, $4$',
    r'1) ложно (нужно равенство накрест лежащих, не сумма $90^\circ$). 2) верно. 3) верно ($70^\circ+110^\circ=180^\circ$). 4) верно.')
add(D, 7, r'$1$, $2$, $4$',
    r'1) ложно (сумма $360^\circ$). 2) ложно (противоположные равны). 3) верно. 4) ложно (недостаточно).')
flush(D)

# ---------- dz_povt7 ----------
D = '8 класс/matvert8-dz_povt7'
add(D, 1, r'$8x^8 y^9$; $2x^2+14xy$',
    r'$(2x^2 y)^3(-xy^3)^2=8x^6 y^3\cdot x^2 y^6=8x^8 y^9$. '
    r'$(-x-7y)^2-(x+7y)(7y-x)=(x+7y)^2-(x+7y)(7y-x)=2x(x+7y)=2x^2+14xy$.')
add(D, 2, r'$a^2(3-a)(9+3a+a^2)$; $(a+b-3)(a+b+3)$',
    r'$27a^2-a^5=a^2(27-a^3)=a^2(3-a)(9+3a+a^2)$. $(a+b)^2-9=(a+b-3)(a+b+3)$.')
add(D, 3, r'$x=2$',
    r'Умножим на $30$: $6(x-2)-5(3x+2)=20-30x$, $-9x-22=20-30x$, $21x=42$, $x=2$.')
add(D, 4, r'$90$ км',
    r'$20t=15(5-t)+30$, $35t=105$, $t=3$, пути $60$ и $30$, всего $90$ км.')
add(D, 5, r'$(-5;-5)$, $(1;-1)$',
    r'$2x-3y=5$. При $y=x$: $x=-5$. При $y=-x$: $x=1$, $y=-1$. Точки $(-5;-5)$ и $(1;-1)$.')
flush(D)

print('batch1 tests/hw done')
