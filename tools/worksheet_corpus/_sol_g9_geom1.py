# noqa: E501
import sys
from pathlib import Path
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from worksheet_corpus.store import load_draft, save_draft

ORIGIN = 'neuro'


def apply_one(did, rows):
    draft = load_draft(did)
    if not draft:
        print('MISS', did)
        return 0
    if draft.get('status') in ('skipped', 'imported'):
        print('SKIP draft', did, draft.get('status'))
        return 0
    els = draft.get('elements') or []
    n = 0
    for row in rows:
        i = row['i']
        if i >= len(els):
            print('BAD index', did, i)
            continue
        el = els[i]
        if el.get('kind') != 'task' or el.get('skip'):
            print('SKIP el', did, i)
            continue
        if (el.get('answer') or '').strip() and (el.get('solution') or '').strip():
            print('ALREADY', did, i)
            continue
        el['answer'] = row['answer']
        el['solution'] = row['solution']
        el['answer_origin'] = ORIGIN
        warn = (row.get('warning') or '').strip()
        if warn:
            warns = list(el.get('warnings') or [])
            if warn not in warns:
                warns.append(warn)
            el['warnings'] = warns
        n += 1
    draft = load_draft(did)
    if not draft or draft.get('status') in ('skipped', 'imported'):
        print('REREAD FAIL', did)
        return 0
    els = draft.get('elements') or []
    for row in rows:
        i = row['i']
        el = els[i]
        if el.get('kind') != 'task' or el.get('skip'):
            continue
        el['answer'] = row['answer']
        el['solution'] = row['solution']
        el['answer_origin'] = ORIGIN
        warn = (row.get('warning') or '').strip()
        if warn:
            warns = list(el.get('warnings') or [])
            if warn not in warns:
                warns.append(warn)
            el['warnings'] = warns
    save_draft(draft)
    print('SAVED', did, 'n=', n)
    return n


I = []


def add(did, i, answer, solution, warning=''):
    I.append({'id': did, 'i': i, 'answer': answer, 'solution': solution,
              'warning': warning})


D = '9 класс/math9-course/geom09-trig-4-resh_treug'
add(D, 2, r'$4\sqrt{2}$ см',
    r'''Третий угол $15^{\circ}$. По теореме синусов
$\dfrac{x}{\sin 135^{\circ}}=\dfrac{4}{\sin 30^{\circ}}$,
$\sin 135^{\circ}=\frac{\sqrt{2}}{2}$, $\sin 30^{\circ}=\frac12$,
откуда $x=4\sqrt{2}$.''')
add(D, 3, r'тупоугольный',
    r'''Большая сторона $7$. Сравниваем $4^2+5^2=41$ и $7^2=49$:
$41<49$, угол против стороны $7$ тупой.''')
add(D, 4, r'$15$ см',
    r'''Пусть стороны, образующие угол $120^{\circ}$, равны $x$ и $x+2$.
Теорема косинусов: $7^2=x^2+(x+2)^2-2x(x+2)\bigl(-\frac12\bigr)$,
$49=3x^2+6x+4$, $x^2+2x-15=0$, $x=3$.
Стороны $3$, $5$, $7$, периметр $15$.''')
add(D, 5, r'$7$ см',
    r'''Медиана к стороне $12$:
$m=\frac12\sqrt{2\cdot 7^2+2\cdot 11^2-12^2}=\frac12\sqrt{196}=7$.''')
add(D, 6, r'$12\sqrt{3}$ см',
    r'''$AB=2R\sin C=24\sin 120^{\circ}=12\sqrt{3}$.
Угол при инцентре $\angle AMB=90^{\circ}+\frac C2=150^{\circ}$,
поэтому $R_{AMB}=\dfrac{AB}{2\sin 150^{\circ}}=12\sqrt{3}$.''')
add(D, 7, r'$8$',
    r'''Искомая сторона $AB$ видна из $C$ и $D$ под $90^{\circ}$,
значит $C$ и $D$ лежат на окружности с диаметром $AB$.
$AD=BC=2$, $CD=7$. В координатах диаметр $2R$:
получаем $2\bigl|R-\frac2R\bigr|=7$, $R=4$, $AB=8$.''')
add(D, 8, r'$13$',
    r'''Биссектриса угла $A$ в $\triangle ABH$ (прямой при $H$)
делит катет $BH$ в отношении $AB:AH=1:\cos A=13:12$.
Отсюда $\cos A=\frac{12}{13}$, $\sin A=\frac{5}{13}$,
$R=\dfrac{BC}{2\sin A}=\dfrac{10}{2\cdot 5/13}=13$.''')
add(D, 10, r'$2$ см',
    r'''$p=21$, $S=\sqrt{21\cdot 1\cdot 6\cdot 14}=42$,
$r=S/p=2$.''')
add(D, 11, r'$1:2$',
    r'''$\dfrac{S_{ABD}}{S_{ACE}}=\dfrac{AB\cdot AD}{AC\cdot AE}=\dfrac{4\cdot 6}{9\cdot 8}=\dfrac13$.
Тогда $S_{BCED}=\frac23 S_{ACE}$ и искомое отношение $1:2$.''')
add(D, 12, r'$90\sqrt{3}$',
    r'''Центроид: $AO=12$, $CO=10$.
$S_{AOC}=\frac12\cdot 12\cdot 10\cdot\sin 120^{\circ}=30\sqrt{3}$.
Треугольники $AOB$, $BOC$, $COA$ равновелики, поэтому
$S_{ABC}=3\cdot 30\sqrt{3}=90\sqrt{3}$.
Или $S=\frac23\cdot 18\cdot 15\cdot\sin 120^{\circ}=90\sqrt{3}$.''')

D = '9 класс/matvert9-geom-dist1-tcos'
add(D, 2, r'$7$; $\sqrt{29}$',
    r'''1) $AC^2=5^2+8^2-2\cdot 5\cdot 8\cdot\cos 60^{\circ}=49$, $AC=7$.
2) $BC^2=3^2+(2\sqrt{2})^2-2\cdot 3\cdot 2\sqrt{2}\cdot\cos 135^{\circ}=29$, $BC=\sqrt{29}$.''')
add(D, 3, r'$45^{\circ}$',
    r'''Средняя сторона $5$.
$\cos=\dfrac{18+49-25}{2\cdot 3\sqrt{2}\cdot 7}=\dfrac{1}{\sqrt{2}}$, угол $45^{\circ}$.''')
add(D, 4, r'нет',
    r'''Косинус большего угла (против $12$):
$\dfrac{49+64-144}{2\cdot 7\cdot 8}=-\dfrac{31}{112}<0$, треугольник тупоугольный.''')
add(D, 5,
    r'$\alpha=75^{\circ}$, $b=\dfrac{10\sin 20^{\circ}}{\sin 75^{\circ}}$, $c=\dfrac{10\sin 85^{\circ}}{\sin 75^{\circ}}$; $\gamma=30^{\circ}$, $a=\dfrac{16\sin 40^{\circ}}{\sin 70^{\circ}}$, $c=\dfrac{8}{\sin 70^{\circ}}$',
    r'''1) $\alpha=75^{\circ}$, теорема синусов $b,c$ через $a=10$.
2) $\gamma=30^{\circ}$, $\sin 110^{\circ}=\sin 70^{\circ}$,
$a=\dfrac{16\sin 40^{\circ}}{\sin 70^{\circ}}$, $c=\dfrac{8}{\sin 70^{\circ}}$.''')
add(D, 6,
    r'$b=\sqrt{100-96\cos 15^{\circ}}$, далее углы по теореме косинусов; $a=\sqrt{74+70\cos 35^{\circ}}$, далее углы по теореме косинусов',
    r'''1) $b^2=8^2+6^2-2\cdot 8\cdot 6\cos 15^{\circ}=100-96\cos 15^{\circ}$,
затем $\cos\alpha$, $\cos\gamma$.
2) $a^2=7^2+5^2-2\cdot 7\cdot 5\cos 145^{\circ}=74+70\cos 35^{\circ}$.''')
add(D, 7, r'$\sqrt{37}$; $2\sqrt{19}$',
    r'''В $\triangle ACD$: $AC^2=10^2+4^2-2\cdot 10\cdot 4\cdot\cos 60^{\circ}=76$, $AC=2\sqrt{19}$.
Угол $C$ трапеции $120^{\circ}$, в $\triangle BCD$:
$BD^2=3^2+4^2-2\cdot 3\cdot 4\cos 120^{\circ}=37$, $BD=\sqrt{37}$.''')
add(D, 8, r'$\sqrt{17}$',
    r'''$AB=5\sqrt{2}$, $AT:TB=1:4$.
В координатах $C(0,0)$, $A(5,0)$, $B(0,5)$ точка $T(4,1)$, $CT=\sqrt{17}$.''')
add(D, 9,
    r'$x=\dfrac{a\cos\gamma\,\sin\varphi}{\cos\alpha\sin\beta\cos\varphi}$, $y=\dfrac{a\cos\gamma}{\cos\alpha\sin\beta\cos\varphi}$; $x=\dfrac{d\tan\beta\cdot\sin\angle ADC}{\sin\alpha}$',
    r'''а) $AB=\dfrac{a}{\cos\alpha}$, $AD=\dfrac{a}{\cos\alpha\sin\beta}$,
$AE=AD\cos\gamma$, далее $x=AE\tan\varphi$, $y=\dfrac{AE}{\cos\varphi}$.
б) В $\triangle ABD$ катет $AD=d\tan\beta$; дальше теорема синусов в $\triangle ADC$.''',
    'На втором рисунке длина $y$ по подписям не восстанавливается однозначно.')
add(D, 10, r'доказано',
    r'''$AB^2+CD^2-BC^2-DA^2=-2\,\overrightarrow{AC}\cdot\overrightarrow{BD}$.
Если $a^2+c^2=b^2+d^2$, то скалярное произведение диагоналей равно нулю.''')
add(D, 11, r'$\dfrac{13}{20}$',
    r'''Свесы $x+y=5$, $y^2-x^2=1$, откуда $y=\frac{13}{5}$, $x=\frac{12}{5}$.
$\cos D=\dfrac{y}{CD}=\dfrac{13}{20}$.''')

D = '9 класс/matvert9-geom-dist2-reshtreug'
add(D, 2, r'$1$ или $3$',
    r'''Теорема косинусов: $13=16+x^2-4x$, $x^2-4x+3=0$, $x=1$ или $x=3$
(неоднозначный случай SAS/SSA).''')
add(D, 3, r'$12$ см',
    r'''$p=21$, $S=\sqrt{21\cdot 8\cdot 7\cdot 6}=84$, $h_{14}=\dfrac{2S}{14}=12$.''')
add(D, 4,
    r'$\dfrac{d\sin\beta}{\sin(\alpha+\beta)}$, $\dfrac{d\sin\alpha}{\sin(\alpha+\beta)}$',
    r'''Диагональ составляет углы $\alpha$ и $\beta$ со сторонами, исходящими из одной вершины.
Из $\overrightarrow{AB}+\overrightarrow{AD}=\overrightarrow{AC}$ проекцией:
$AB=\dfrac{d\sin\beta}{\sin(\alpha+\beta)}$, $AD=\dfrac{d\sin\alpha}{\sin(\alpha+\beta)}$.''')
add(D, 5, r'$\dfrac{25}{3}$ см',
    r'''Высота $\sqrt{10^2-8^2}=6$, $S=48$,
$R=\dfrac{10\cdot 10\cdot 16}{4\cdot 48}=\dfrac{25}{3}$.''')
add(D, 6,
    r'$\dfrac{5\sin 60^{\circ}}{\sin 100^{\circ}}$, $\dfrac{5\sin 20^{\circ}}{\sin 100^{\circ}}$',
    r'''Дуги между точками касания имеют меры $180^{\circ}-A$ и относятся как $2:3:4$.
Углы $100^{\circ}$, $60^{\circ}$, $20^{\circ}$. Большая сторона против $100^{\circ}$ равна $5$,
остальные — по теореме синусов.''')
add(D, 7,
    r'$\dfrac{2m}{\sin(\alpha+\beta)}\sqrt{\sin^2\alpha+\sin^2\beta-2\sin\alpha\sin\beta\cos(\alpha+\beta)}$',
    r'''В координатах с вершиной в начале медианы:
$b=\dfrac{2m\sin\alpha}{\sin(\alpha+\beta)}$, $c=\dfrac{2m\sin\beta}{\sin(\alpha+\beta)}$,
далее теорема косинусов для стороны против угла $\alpha+\beta$.''')
add(D, 8,
    r'$\dfrac{4\,AB\sin\frac{\alpha}{2}}{1+2\sin\frac{\alpha}{2}}\cos\bigl(45^{\circ}-\frac{\alpha}{4}\bigr)$',
    r'''$AB=BC$, $\angle A=\angle C=90^{\circ}-\frac{\alpha}{2}$, $AC=2\,AB\sin\frac{\alpha}{2}$.
Длина биссектрисы из $A$: $\ell=\dfrac{2\cdot AB\cdot AC}{AB+AC}\cos\frac{A}{2}$.''',
    'В условии нет длины стороны; ответ через боковую $AB$.')
add(D, 9, r'$3$',
    r'''По свойству биссектрисы $OM:OP=MK:KP=2:3$.
$OM+OP=15$, поэтому $OM=6$, $OP=9$, разность $3$.''')
add(D, 10, r'$\dfrac{2\sqrt{510}}{15}$',
    r'''Вписанные углы $\angle NMP=\angle PMQ$ стягивают равные дуги, хорды $NP=PQ$.
Теорема косинусов: $37-12\cos\varphi=40-24\cos\varphi$, $\cos\varphi=\frac14$,
$\sin\varphi=\frac{\sqrt{15}}{4}$. Тогда $\sqrt{34}=2R\sin\varphi$,
$R=\dfrac{2\sqrt{34}}{\sqrt{15}}=\dfrac{2\sqrt{510}}{15}$.''')
add(D, 11, r'$120^{\circ}$',
    r'''$\ell=\dfrac{2bc}{b+c}\cos\frac{A}{2}$ и $\frac1b+\frac1c=\frac1\ell$ дают
$\ell=\dfrac{bc}{b+c}$, откуда $\cos\frac{A}{2}=\frac12$, $A=120^{\circ}$.''')

D = '9 класс/matvert9-geom-med_vys_biss'
add(D, 0, r'$12$ см',
    r'''$p=21$, $S=84$, $h_{14}=12$.''')
add(D, 1, r'$\dfrac{7}{2}$',
    r'''Третья сторона: $a^2=9+25-15=19$.
$m_a=\frac12\sqrt{2\cdot 9+2\cdot 25-19}=\frac72$.''')
add(D, 2, r'$2$',
    r'''$4m^2=2\cdot 4+2\cdot 16-a^2$ даёт $a^2=20-8\sqrt{3}$.
С другой стороны $a^2=20-16\cos\theta$, $\cos\theta=\frac{\sqrt{3}}{2}$,
$S=4\sin\theta=2$.''')
add(D, 3,
    r'$\dfrac{4\,AB\sin\frac{\alpha}{2}}{1+2\sin\frac{\alpha}{2}}\cos\bigl(45^{\circ}-\frac{\alpha}{4}\bigr)$',
    r'''Как в равнобедренном треугольнике с вершиной $B$: биссектриса из $A$ к стороне $BC$.''',
    'В условии нет длины стороны; ответ через боковую $AB$.')
add(D, 4, r'$3$',
    r'''$OM:OP=8:12=2:3$, $OM+OP=15$, разность $3$.''')
add(D, 5, r'$\dfrac{2\sqrt{510}}{15}$',
    r'''Равные углы при $M$ дают равные дуги и $NP=PQ$, $\cos\varphi=\frac14$,
$R=\dfrac{2\sqrt{510}}{15}$.''')
add(D, 6, r'$2\sqrt{6}$ см',
    r'''$p=9$, $S=\sqrt{9\cdot 2\cdot 3\cdot 4}=6\sqrt{6}$, $h_6=\dfrac{2S}{6}=2\sqrt{6}$.''')
add(D, 7, r'$2\sqrt{3+\sqrt{6}}$',
    r'''$a^2=16+32-16\sqrt{6}=16(3-\sqrt{6})$.
$m_a=\frac12\sqrt{32+64-a^2}=2\sqrt{3+\sqrt{6}}$.''')
add(D, 8, r'$135^{\circ}$',
    r'''Пусть высота делит сторону на $3$ и $10$.
$\tan\frac{\varphi}{\text{частей}}=\frac32$ и $5$,
$\tan\varphi=\dfrac{\frac32+5}{1-\frac32\cdot 5}=-1$, $\varphi=135^{\circ}$.''')


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
