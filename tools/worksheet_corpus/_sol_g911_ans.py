# noqa: E501
"""Ответы по подпунктам 9/11 (решения уже есть). Не коммитить."""
import sys
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from worksheet_corpus._apply_agent_solutions import apply_solutions

I = []


def add(did, i, answers, warning=''):
    I.append({
        'id': did, 'i': i, 'answer': '', 'solution': '',
        'subitem_answers': answers, 'warning': warning,
    })


# --- 11 класс: diagn + уравнения + стереометрия ---
D = '11 класс/diagn2024-01'
add(D, 6, [r'$-15$', r'$-15$'])
add(D, 13, [r'доказано', r'$108\sqrt{3}$'])
add(D, 16, [r'доказано', r'$\dfrac{19\sqrt{3}-\sqrt{111}}{9}$'])

D = '11 класс/ege06-irrats_ur'
add(D, 10, [r'$1;\ \dfrac{1}{4}$', r'$1;\ -\dfrac{57}{101}$', r'$-1;\ -\dfrac{16}{3}$'])

D = '11 класс/ege06-kv_ur'
add(D, 2, [r'$0;\ 2$', r'$\pm 3$', r'$-5;\ 2$'])
add(D, 3, [
    r'$1;\ \dfrac{1}{2}$', r'$1;\ 5$', r'$-1;\ \dfrac{1}{5}$',
    r'$1;\ \dfrac{1}{99}$', r'$-1;\ \dfrac{9}{5}$', r'$\dfrac{1}{2};\ 2$',
])
add(D, 4, [r'$6;\ \dfrac{3}{2}$', r'$\dfrac{1}{2};\ -\dfrac{7}{2}$', r'$-4;\ -3;\ 1$', r'$-6;\ \pm 2$'])
add(D, 6, [r'$1;\ -\dfrac{1}{3}$', r'$5$', r'$2;\ \dfrac{2}{3}$', r'$0;\ 8$'])

D = '11 класс/ege14-volumes'
add(D, 0, [r'доказано', r'$\dfrac{1075}{9}$'])

D = '11 класс/ege19-integers'
add(D, 3, [r'нет решений', r'нет решений'])

# --- 11 класс в каталоге «6 класс» ---
D = '6 класс/math11-ner_ege'
add(D, 8, [
    r'$\bigl(0;\frac{1}{64}\bigr)\cup\{4\}\cup(64;+\infty)$',
    r'$\bigl(0;\frac{1}{64}\bigr)\cup\{4\}\cup(64;+\infty)$',
])
add(D, 15, [
    r'$\bigl(0;\frac{1}{27}\bigr]\cup\bigl[\frac{1}{8};1\bigr)$',
    r'$\bigl(0;\frac{1}{27}\bigr]\cup\bigl[\frac{1}{8};1\bigr)$',
])

D = '6 класс/math11-planim'
add(D, 0, [r'доказано', r'$2:3$'])
add(D, 1, [r'доказано', r'$6{,}75$'])
add(D, 2, [r'доказано', r'$9$'])
add(D, 3, [r'доказано', r'$6$'])
add(D, 4, [r'доказано', r'$\dfrac{3\sqrt{21}}{14}$'])
add(D, 5, [r'доказано', r'$40$'])
add(D, 6, [r'доказано', r'$4$'])
add(D, 7, [r'доказано', r'$10$'])
add(D, 8, [r'доказано', r'$10$'])
add(D, 9, [r'доказано', r'$4{,}5$'])
add(D, 10, [r'доказано', r'$7$'])
add(D, 11, [r'доказано', r'$2\sqrt{281}$'])
add(D, 12, [r'доказано', r'$\sqrt{35}$'])
add(D, 13, [r'доказано', r'$16\sqrt{3}$'])

D = '6 класс/math11-stereom'
add(D, 0, [r'доказано', r'$324\dfrac{5}{8}$'])
add(D, 1, [r'доказано', r'$\operatorname{arctg}\dfrac{\sqrt{10}}{3}$'])
add(D, 2, [r'доказано', r'$9\sqrt{3}$'])
add(D, 3, [r'доказано', r'$20\sqrt{3}$'])
add(D, 4, [r'доказано', r'$\sqrt{2}$'])
add(D, 5, [r'доказано', r'$\arcsin\dfrac{\sqrt{70}}{21}$'])
add(D, 6, [r'доказано', r'$4\dfrac{8}{13}$'])
add(D, 7, [r'доказано', r'$\arccos\dfrac{\sqrt{21}}{21}$'])
add(D, 8, [r'доказано', r'$\dfrac{15}{17}$'])
add(D, 9, [r'доказано', r'$4\pi$'])
add(D, 10, [r'доказано', r'$\dfrac{3\sqrt{6}}{2}$'])

# --- 9 класс: функции и графики ---
D = '9 класс/math9-course/alg09-func-01'
add(D, 3, [r'чётная (доказано)', r'нечётная (доказано)', r'общего вида (доказано)'])
add(D, 8, [
    r'ограничена снизу ($y\geqslant -2$), сверху нет',
    r'ограничена сверху ($y\leqslant 3$), снизу нет',
    r'ограничена: $y\in\bigl[\frac12;1\bigr)$',
])
add(D, 51, [
    r'отражение $f$ относительно $Oy$, асимптоты $x=-1$, $y=2$',
    r'$y=2-\dfrac{8}{x-2}$, асимптота $x=2$',
    r'части графика ниже $Ox$ отражены вверх',
    r'график при $x\geqslant 0$ отражён влево, $x\ne\pm 1$',
])

D = '9 класс/math9-course/alg09-ur_2per'
add(D, 2, [
    r'лучи $y=\pm x$ при $x\geqslant 0$',
    r'тот же угол с вершиной $(2;1)$',
    r'лучи $y=\pm x$ при $x\geqslant 0$',
    r'прямые $y=\pm x$',
    r'прямые $y=x+5$ и $y=-x-1$',
    r'$y=\dfrac{1}{|x|}$ ($x\ne 0$)',
    r'$x=\dfrac{1}{|y|}$ ($y\ne 0$)',
    r'$xy=\pm 1$ (четыре ветви)',
])
add(D, 4, [
    r'полупарабола $y=\sqrt{x}$',
    r'правая половина $y=x^2$',
    r'правая половина $y=x^2+1$',
    r'правая половина $y=-x^2$',
    r'правые половины $y=\pm x^2$',
    r'$|y|=x^2-1$ при $x\geqslant 1$',
    r'$y+1=\pm(x-1)^2$',
    r'сдвиг предыдущего, $|x|\geqslant 1$',
    r'определено при $|x|\geqslant 2$',
])
add(D, 6, [
    r'парабола $y=x^2$ без $(0;0)$ и $(1;1)$',
    r'парабола $y=x^2$ без $(0;0)$ и $(1;1)$',
])

D = '9 класс/math9-course/apo-math-wave10-3'
add(D, 15, [
    r'$798{,}6$ г и $793{,}9$ г',
    r'дисперсии $17{,}44$ и $1{,}69$',
    r'автомат 2',
])

D = '9 класс/matvert8-alg-func-povt'
add(D, 8, [
    r'$x=-3,\ 2,\ 5$',
    r'$f_{\max}=2{,}5$, $f_{\min}=-1{,}5$',
    r'$f>0$ на $(-3;2)\cup(5;6]$, $f<0$ на $[-5;-3)\cup(2;5)$',
    r'возрастает до $\approx 0$, убывает до $\approx 3{,}7$, затем возрастает',
])
add(D, 9, [
    r'$D=\mathbb{R}$, $E=[4;+\infty)$, нулей нет, убывает на $(-\infty;0]$, возрастает на $[0;+\infty)$',
    r'$D=E=\mathbb{R}\setminus\{\pm 2\}$, нуль $x=0$, прямая $y=x$ с выколами',
    r'$D=\mathbb{R}$, $E=\bigl[\frac{15}{4};+\infty)$, нулей нет, вершина $\bigl(-\frac12;\frac{15}{4}\bigr)$',
    r'$D=[4;+\infty)$, $E=[0;+\infty)$, нуль $x=4$, возрастает',
    r'$D=\mathbb{R}$, $E=[0;+\infty)$, нули $\pm 3$',
    r'при $x\geqslant 0$: $x^2-4x$; при $x<0$: $-x^2-2x$',
])
add(D, 11, [
    r'$D=E=\mathbb{R}$, нуль $\frac14$, $f(0)=-2$, $f(2)=14$, $f=-16$ при $x=-\frac74$',
    r'$D=\mathbb{R}$, $E=[-16;+\infty)$, нули $0$ и $8$, $f(0)=0$, $f(2)=-12$, $f=-16$ при $x=4$',
    r'$D=\mathbb{R}$, $E=[8;+\infty)$, нулей нет, $f(0)=10$, $f(2)=8$, $f=-16$ корней нет',
    r'$D=\mathbb{R}\setminus\{-3\}$, $E=\mathbb{R}\setminus\{2\}$, нуль $-\frac52$, $f(0)=\frac53$, $f(2)=\frac95$, $f=-16$ при $x=-\frac{53}{18}$',
])

D = '9 класс/matvert9-alg-issl_func'
add(D, 1, [
    r'вершина $(-2;5)$, $E=(-\infty;5]$',
    r'при $x\geqslant 4$: $x^2-4x$; при $x<4$: $4x-x^2$',
    r'угол с вершиной $\bigl(\frac43;3\bigr)$',
    r'на $[0;+\infty)$ парабола $x^2-x-6$',
    r'$E=\bigl(-1;-\frac12\bigr]$',
])
add(D, 5, [
    r'вершина $(2;2)$',
    r'при $x\geqslant -2$: $x(x+2)$; при $x<-2$: $-x^2-2x$',
    r'угол с вершиной $(-2;3)$',
    r'$E=[4;+\infty)$',
    r'гипербола $y=-1-\dfrac{3}{x-2}$ с выколами $x=2$ и $x=6$',
])

D = '9 класс/matvert9-alg-syst_ner'
add(D, 1, [
    r'$(-3;-1]$',
    r'$(-3;-1)$',
    r'$(-3;-1)$',
    r'$[-3;-1]$',
])

D = '9 класс/matvert9-dz1-povt-group1'
add(D, 1, [
    r'$10;\ -\dfrac{6}{13};\ \dfrac{8}{11};\ 0$',
    r'$0$',
])

D = '9 класс/matvert9-teorver-bernulli'
add(D, 13, [r'$0{,}21$', r'$0{,}91$', r'$0{,}21$', r'$0{,}91$'])
add(D, 14, [r'нет', r'да', r'нет', r'да'])

D = '9 класс/oge-tren-18_05_22'
add(D, 6, [r'да', r'нет', r'нет', r'нет'])

D = '9 класс/oge-tren-19_05_22'
add(D, 6, [r'нет', r'нет', r'нет', r'да'])

D = '9 класс/КР 9 класс геометрия/matvert9-kr1-resh_treug'
add(D, 0, [r'неверно', r'верно', r'верно', r'неверно'])
add(D, 9, [r'неверно', r'верно', r'верно', r'неверно'])
add(D, 14, [r'неверно', r'неверно', r'неверно', r'неверно'])


if __name__ == '__main__':
    apply_solutions(I)
