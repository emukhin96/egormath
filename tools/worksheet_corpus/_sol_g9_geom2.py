# noqa: E501
import sys
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from worksheet_corpus._sol_g9_geom1 import apply_one, add, I

D = '9 класс/matvert9-geom-sr-t_sin'
add(D, 1, r'$7\sqrt{3}$',
    r'''$\angle A=75^{\circ}$. $AC$ против $60^{\circ}$, $AB$ против $45^{\circ}$:
$AC=7\sqrt{2}\cdot\dfrac{\sin 60^{\circ}}{\sin 45^{\circ}}=7\sqrt{3}$.''')
add(D, 2, r'$60^{\circ}$ или $120^{\circ}$',
    r'''$\dfrac{\sin B}{9}=\dfrac{\sin 30^{\circ}}{3\sqrt{3}}$, $\sin B=\dfrac{\sqrt{3}}{2}$.
Оба угла $60^{\circ}$ и $120^{\circ}$ допустимы.''')
add(D, 3, r'$\sqrt{10}$ или $\sqrt{58}$',
    r'''Пусть третья сторона $x$, тогда $x=R\sqrt{2}$ и $\sin X=\frac{\sqrt{2}}{2}$,
$X=45^{\circ}$ или $135^{\circ}$.
$x^2=18+16-24\sqrt{2}\cos X$: при $45^{\circ}$ имеем $\sqrt{10}$, при $135^{\circ}$ — $\sqrt{58}$.''')
add(D, 5, r'$5$',
    r'''$\angle A=105^{\circ}$. $AC=5\sqrt{2}\cdot\dfrac{\sin 30^{\circ}}{\sin 45^{\circ}}=5$.''')
add(D, 6, r'$60^{\circ}$ или $120^{\circ}$',
    r'''$\dfrac{\sin A}{2\sqrt{3}}=\dfrac{\sin 30^{\circ}}{2}$, $\sin A=\dfrac{\sqrt{3}}{2}$.
Оба случая дают треугольник.''')
add(D, 7, r'$2\sqrt{7}$ или $2\sqrt{31}$',
    r'''$x=R$ $\Rightarrow$ $\sin X=\frac12$, $X=30^{\circ}$ или $150^{\circ}$.
$x^2=76-32\sqrt{3}\cos X$: $2\sqrt{7}$ или $2\sqrt{31}$.''')

D = '9 класс/matvert9-geom-t_cos'
add(D, 0, r'$7$; $\sqrt{29}$',
    r'''а) $AC^2=25+64-40=49$, $AC=7$.
б) $BC^2=9+8+12=29$, $BC=\sqrt{29}$.''')
add(D, 1, r'$45^{\circ}$',
    r'''Средняя сторона $5$, $\cos=\frac{1}{\sqrt{2}}$, угол $45^{\circ}$.''')
add(D, 2, r'нет',
    r'''$\cos$ угла против $12$ равен $-\frac{31}{112}<0$.''')
add(D, 3,
    r'$\alpha=75^{\circ}$, $b=\dfrac{10\sin 20^{\circ}}{\sin 75^{\circ}}$, $c=\dfrac{10\sin 85^{\circ}}{\sin 75^{\circ}}$; $\gamma=30^{\circ}$, $a=\dfrac{16\sin 40^{\circ}}{\sin 70^{\circ}}$, $c=\dfrac{8}{\sin 70^{\circ}}$',
    r'''Теорема синусов после нахождения третьего угла.''')
add(D, 4,
    r'$b=\sqrt{100-96\cos 15^{\circ}}$; $a=\sqrt{74+70\cos 35^{\circ}}$',
    r'''Теорема косинусов для стороны против данного угла, затем остальные углы.''')
add(D, 5, r'$2\sqrt{7}$; $4\sqrt{7}$',
    r'''а) $BC^2=48+4-24=28$, $BC=2\sqrt{7}$.
б) $BC^2=16+64+32=112$, $BC=4\sqrt{7}$.''')
add(D, 6, r'$\arccos\dfrac{19}{33}$',
    r'''Средняя сторона $9$:
$\cos=\dfrac{36+121-81}{2\cdot 6\cdot 11}=\dfrac{19}{33}$.''')
add(D, 7, r'да',
    r'''Косинус угла против $8$: $\dfrac{16+49-64}{56}=\dfrac{1}{56}>0$, все углы острые.''')
add(D, 8,
    r'$b=\sqrt{100-96\cos 15^{\circ}}$; $a=\sqrt{74+70\cos 35^{\circ}}$',
    r'''Как в задаче про две стороны и угол между ними.''')
add(D, 9, r'$\sqrt{37}$; $2\sqrt{19}$',
    r'''$AC=2\sqrt{19}$ из $\triangle ACD$; $BD=\sqrt{37}$ из $\triangle BCD$ с углом $120^{\circ}$.''')
add(D, 10, r'$\sqrt{17}$',
    r'''Изосceleсный прямоугольный, $T$ делит гипотенузу $1:4$, $CT=\sqrt{17}$.''')
add(D, 11,
    r'$x=\dfrac{a\cos\gamma\sin\varphi}{\cos\alpha\sin\beta\cos\varphi}$, $y=\dfrac{a\cos\gamma}{\cos\alpha\sin\beta\cos\varphi}$',
    r'''Цепочка прямоугольных треугольников от катета $a$ до $AE$, затем $x=AE\tan\varphi$, $y=AE/\cos\varphi$.''')

D = '9 класс/matvert9-geom-t_cos_povt'
add(D, 0, r'$\sqrt{37}$; $\sqrt{106}$',
    r'''а) $AC^2=16+49-28=37$.
б) $AC^2=50+16+40=106$.''')
add(D, 1, r'$9$ или $3\sqrt{17}$',
    r'''$\cos=\pm\frac13$.
$x^2=117\mp 36$: $81$ или $153$.''')
add(D, 2, r'$9$, $15$, $21$',
    r'''Стороны $3k$, $5k$, третья $7k$ (косинус $120^{\circ}$).
$15k=45$, $k=3$.''')
add(D, 3, r'$\sqrt{39}$',
    r'''В $\triangle BIC$ угол $90^{\circ}+\frac A2=120^{\circ}$, $IB=2$, $IC=5$.
$BC^2=4+25+10=39$.''')
add(D, 4, r'$\dfrac{13}{112}$',
    r'''Свесы $x+y=7$, $y^2-x^2=36$, $x=\frac{13}{14}$.
$\cos A=\dfrac{x}{8}=\dfrac{13}{112}$.''')
add(D, 5, r'$4\sqrt{3}$; $4\sqrt{3+\sqrt{2}}$',
    r'''а) $BC^2=48+144-144=48$, $BC=4\sqrt{3}$.
б) $BC^2=32+16+16\sqrt{2}=16(3+\sqrt{2})$.''')
add(D, 6, r'$6$, $16$, $14$',
    r'''Стороны $3k$, $8k$, третья $7k$. Периметр $18k=36$, $k=2$.''')
add(D, 7, r'$\sqrt{58}$',
    r'''В $\triangle AIC$ угол $90^{\circ}+\frac B2=135^{\circ}$.
$AC^2=18+16+24=58$.''')

D = '9 класс/matvert9-geom-t_sin'
add(D, 0, r'$5\sqrt{2}$; $3$',
    r'''а) $\angle C=75^{\circ}$, $AC=5\sqrt{3}\cdot\dfrac{\sin 45^{\circ}}{\sin 60^{\circ}}=5\sqrt{2}$.
б) $\angle B=30^{\circ}$, $AC=3\sqrt{2}\cdot\dfrac{\sin 30^{\circ}}{\sin 135^{\circ}}=3$.''')
add(D, 1, r'$30^{\circ}$ (одно); $60^{\circ}$ или $120^{\circ}$ (два)',
    r'''а) $\sin C=\frac12$; угол $150^{\circ}$ не укладывается, одно решение $30^{\circ}$.
б) $\sin C=\frac{\sqrt{3}}{2}$, оба $60^{\circ}$ и $120^{\circ}$ возможны.''')
add(D, 2, r'$6$ см',
    r'''$R=\dfrac{AB}{2\sin C}=\dfrac{6}{2\cdot\frac12}=6$.''')
add(D, 3, r'$9$ см',
    r'''$\angle AHB=180^{\circ}-C$, поэтому
$R_{AHB}=\dfrac{AB}{2\sin C}=R_{ABC}=9$.''')
add(D, 4, r'$\dfrac{25}{4}$ см',
    r'''Высота $8$, $S=48$, $R=\dfrac{10\cdot 10\cdot 12}{4\cdot 48}=\dfrac{25}{4}$.''')
add(D, 5, r'$5$ см',
    r'''У равнобокой трапеции с перпендикулярными диагоналями $h=\frac{a+b}{2}$
и $a^2+b^2=2\ell^2=100$. Центр на оси:
$R^2=\frac{a^2+b^2}{4}=25$, $R=5$.''')
add(D, 6, r'$4$; $4\sqrt{3}$',
    r'''а) $BC=4\sqrt{2}\cdot\dfrac{\sin 30^{\circ}}{\sin 45^{\circ}}=4$.
б) $BC=4\sqrt{2}\cdot\dfrac{\sin 120^{\circ}}{\sin 45^{\circ}}=4\sqrt{3}$.''')
add(D, 7, r'$5$ см',
    r'''$R=\dfrac{BC}{2\sin A}=\dfrac{5\sqrt{3}}{2\cdot\sin 120^{\circ}}=5$.''')
add(D, 8, r'$\dfrac{169}{24}$ см',
    r'''Высота $12$, $S=60$, $R=\dfrac{13\cdot 13\cdot 10}{240}=\dfrac{169}{24}$.''')

D = '9 класс/matvert9-geom-t_sin2'
add(D, 0, r'$\dfrac{85}{8}$ см',
    r'''Ноги $10$, основания $21$ и $9$, высота $8$.
Центр на оси: $R^2=\bigl(\frac{21}{2}\bigr)^2+\bigl(\frac{13}{8}\bigr)^2=\bigl(\frac{85}{8}\bigr)^2$.''')
add(D, 1,
    r'$\dfrac{3}{2}$, $\dfrac{25}{8}$; $\dfrac{\sqrt{231}}{2}$, $\dfrac{1885}{8\sqrt{231}}$',
    r'''а) $p=8$, $S=12$, $r=\frac32$, $R=\frac{25}{8}$.
б) $p=40$, $S=20\sqrt{231}$, $r=\frac{\sqrt{231}}{2}$,
$R=\dfrac{25\cdot 26\cdot 29}{80\sqrt{231}}=\dfrac{1885}{8\sqrt{231}}$.''')
add(D, 2, r'$\dfrac{6\sqrt{3}}{7+\sqrt{13}}$, $\dfrac{\sqrt{39}}{3}$',
    r'''Третья сторона $\sqrt{13}$, $S=3\sqrt{3}$,
$r=\dfrac{6\sqrt{3}}{7+\sqrt{13}}$, $R=\dfrac{\sqrt{13}}{\sqrt{3}}=\dfrac{\sqrt{39}}{3}$.''')
add(D, 3, r'$\dfrac{48}{5}$ см',
    r'''Диагональ-биссектриса острого угла даёт $AB=BC$.
Основания $5k$, $11k$, высота $4k$, диагональ $4\sqrt{5}\,k$.
$R=\frac{5\sqrt{5}}{2}k=6$, $k=\frac{12}{5\sqrt{5}}$, диагональ $\frac{48}{5}$.''')
add(D, 4, r'$\dfrac{2\sqrt{35}}{7}$, $\dfrac{36\sqrt{35}}{35}$',
    r'''Равнобедренный $12$, $12$, $4$. Высота $2\sqrt{35}$, $S=4\sqrt{35}$,
$r=\frac{2\sqrt{35}}{7}$, $R=\frac{36\sqrt{35}}{35}$.''')
add(D, 5,
    r'$\dfrac{27\sqrt{2}}{15+3\sqrt{13-6\sqrt{2}}}$, $\dfrac{3\sqrt{13-6\sqrt{2}}}{\sqrt{2}}$',
    r'''Третья сторона $3\sqrt{13-6\sqrt{2}}$, $S=\frac{27\sqrt{2}}{2}$,
$R=\dfrac{x}{\sqrt{2}}$, $r=\dfrac{2S}{15+x}$.''')


def main():
    from collections import OrderedDict
    by = OrderedDict()
    for row in I:
        by.setdefault(row['id'], []).append(row)
    total = 0
    for did, rows in by.items():
        total += apply_one(did, rows)
    print('FILLED', total)


if __name__ == '__main__':
    main()
