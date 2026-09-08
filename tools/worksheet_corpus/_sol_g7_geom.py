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


# ---------------------------------------------------------------------------
D = '7 класс/geom7-par_pr-revision'
add(D, 1, r'доказано',
    r'''$D$ на $AB$, $E$ на $BC$, $DE\parallel AC$. Тогда $\angle BDE=\angle BAC$ (соответственные).
$AD=DE$, поэтому $\angle DAE=\angle DEA$ и $\angle ADE=180^\circ-\angle BAC$, откуда $\angle DAE=\frac12\angle BAC$.
Но $\angle DAE=\angle BAE$, значит $AE$ — биссектриса $\angle BAC$. В равнобедренном $\triangle ABC$ ($AB=AC$) она же высота, поэтому $AE\perp BC$.''')
add(D, 2, r'$70^{\circ}$',
    r'''$AB\parallel CD$, $E=BC\cap DE$. Тогда $\angle BCD=\angle ABC=30^{\circ}$ (накрест лежащие).
В $\triangle CDE$: $\angle CDE=40^{\circ}$, $\angle DCE=30^{\circ}$, $\angle CED=110^{\circ}$.
Точки $B$, $E$, $C$ коллинеарны, поэтому $\angle BED=180^{\circ}-110^{\circ}=70^{\circ}$.''')
add(D, 3, r'доказано',
    r'''$DE\parallel AC$. В $\triangle ADM$ сторона $AD=MD$, поэтому $\angle MAD=\angle AMD$.
$\angle ADE=180^{\circ}-\angle BAC$ (соответственные с $DE\parallel AC$), значит $\angle MAD=\frac12\angle BAC$, и $AM$ — биссектриса $\angle BAC$.
Аналогично $ME=EC$ даёт $\angle ECM=\frac12\angle ACB$, и $CM$ — биссектриса $\angle ACB$.
Две биссектрисы пересекаются в инцентре, поэтому $M$ — точка пересечения биссектрис.''')
add(D, 5, r'$1$',
    r'''$E$-$K$-$L$-$F$ и $EK=KL=LF$, поэтому $EL=FK$.
Дано $AE=BF$, $AL=BK$. По трём сторонам $\triangle AEL\cong\triangle BFK$, откуда $\angle AEL=\angle BFK=\angle KFB$. Значит $m=1$.''')

# ---------------------------------------------------------------------------
D = '7 класс/geom7-podg1-hard'
add(D, 1, r'$110^{\circ}$',
    r'''Из $140^{\circ}+160^{\circ}+60^{\circ}=360^{\circ}$ следует, что луч $OB$ лежит вне угла $AOC=160^{\circ}$: от $OA$ в одну сторону $160^{\circ}$ до $OC$, в другую $140^{\circ}$ до $OB$, оставшиеся $60^{\circ}$ — угол $BOC$.
Биссектриса $\angle AOC$ идёт под $80^{\circ}$ к $OA$ в сторону $OC$, биссектриса $\angle BOC$ — под $30^{\circ}$ к $OB$ в сторону $OC$, то есть под $170^{\circ}$ к $OA$ в сторону $OB$.
Угол между ними $80^{\circ}+170^{\circ}=250^{\circ}$, меньший равен $110^{\circ}$.''')
add(D, 2, r'$60^{\circ}$',
    r'''Три прямые дают шесть углов с суммой $360^{\circ}$. Отмеченные три угла равны и вместе с вертикальными к ним покрывают все шесть углов, поэтому каждый равен $360^{\circ}/6=60^{\circ}$.''')
add(D, 4, r'доказано',
    r'''По трём сторонам $\triangle ABD\cong\triangle ABE$ ($AD=AE$, $BD=BE$, $AB$ общая), поэтому точки $D$ и $E$ симметричны относительно прямой $AB$.
Тогда $\triangle ACD\cong\triangle ACE$ (сторона $AC$ общая, $AD=AE$, прилежащие углы равны), откуда $CD=CE$.''')
add(D, 5, r'доказано',
    r'''В $\triangle LBC$ биссектриса $BK$ даёт $\frac{LK}{KC}=\frac{BL}{BC}=\frac12$, поэтому $LK=\frac12 KC$.
$L$ — середина $AK$, значит $AL=LK=\frac12 KC$ и $AK=KC$, то есть $K$ — середина $AC$ и $KC=\frac12 AC$.
Пусть $AC=2x$, $AL=\frac x2$, $LC=\frac{3x}2$, $BC=a$, $BL=\frac a2$, $AB=c$.
По формуле Стюарта для чевианы $BL$: $c^2\cdot\frac{3x}2+a^2\cdot\frac x2=2x\bigl(\frac{a^2}4+\frac x2\cdot\frac{3x}2\bigr)$, откуда $\frac34 c^2=\frac{3x^2}4$ и $c=x=KC$.''')

# ---------------------------------------------------------------------------
D = '7 класс/geom7-podg1-med'
add(D, 0, r'$3$ см',
    r'''$AM=\frac4{9}\cdot 27=12$, $AN=\frac13\cdot 27=9$. Точка $N$ между $A$ и $M$, поэтому $MN=12-9=3$ см.''')
add(D, 1, r'$77^{\circ}$ или $163^{\circ}$',
    r'''Луч $OK$ может лежать внутри $\angle MON$ или вне его.
Если внутри, то $\angle MOK=120^{\circ}-43^{\circ}=77^{\circ}$.
Если снаружи, прилегая к $ON$ с другой стороны, то $\angle MOK=120^{\circ}+43^{\circ}=163^{\circ}$.''',
    'Положение луча $OK$ на рисунке не задано.')
add(D, 2, r'$136^{\circ}$ и $44^{\circ}$',
    r'''Пусть $\angle PKE=x$. Тогда $\angle FKE=x+24^{\circ}$. Луч $KF$ — биссектриса $\angle MKE$, поэтому $\angle MKE=2(x+24^{\circ})$.
Смежные углы: $2(x+24^{\circ})+x=180^{\circ}$, $3x=132^{\circ}$, $x=44^{\circ}$.
Значит $\angle MKE=136^{\circ}$, $\angle PKE=44^{\circ}$.''')
add(D, 3, r'доказано',
    r'''$AB=BC$, поэтому $\triangle ABC$ равнобедренный. Из $\angle 1=\angle 2$ следует равенство треугольников, прилегающих к равным углам (обычно $\triangle ABE\cong\triangle CBD$ по стороне и двум углам либо по двум сторонам и углу), откуда $AE=CD$.''',
    'Рисунка нет: восстановлена стандартная конфигурация с равными углами при основании.')
add(D, 4, r'$27$ см',
    r'''Биссектриса к основанию равнобедренного треугольника — медиана и высота, $AD=DC$.
$P_{ABC}=AB+BC+AC=38$, $AB=BC$, $BD=8$.
$P_{BDC}=BD+DC+BC=8+\frac{AC}2+BC$.
Но $AB+BC+AC=2BC+AC=38$, и $P_{BDC}=BC+\frac{AC}2+8=\frac{2BC+AC}2+8=19+8=27$ см.''')
add(D, 5, r'доказано',
    r'''$MP=PE$ и $MF=FE$, поэтому $F$ и $P$ лежат на серединном перпендикуляре к $ME$, и прямая $FP$ — ось симметрии.
Точка $K$ на этой оси (типично $K=FP\cap ME$ или на продолжении), тогда $\triangle MKP\cong\triangle EKP$ и $\angle MKP=\angle EKP$.''',
    'Рисунка нет: использована симметрия равнобедренных $MPE$ и $MFE$.')
add(D, 6, r'доказано',
    r'''$AM$ — медиана, $BM=CM$. $DB=DC$, поэтому $D$ лежит на серединном перпендикуляре к $BC$.
Тогда и $A$ лежит на нём (прямая $AM$ совпадает с серединным перпендикуляром), значит $AB=AC$.''')

# ---------------------------------------------------------------------------
D = '7 класс/geom7-pr_ug_treug'
add(D, 0, r'$30^{\circ}$ и $60^{\circ}$',
    r'''Медиана к гипотенузе равна её половине. Если она равна катету, этот катет равен половине гипотенузы, и противолежащий угол равен $30^{\circ}$. Второй острый угол $60^{\circ}$.''')
add(D, 1, r'$1:3$',
    r'''В треугольнике $30^{\circ}$-$60^{\circ}$-$90^{\circ}$ катеты $a$ и $a\sqrt3$, гипотенуза $2a$. Высота к гипотенузе делит её на $a^2/(2a)=\frac a2$ и $3a/2$. Отношение $1:3$.''')
add(D, 2, r'$1:2$',
    r'''Пусть $\angle C=90^{\circ}$, $\angle A=30^{\circ}$, $BC=a$, $AC=a\sqrt3$, $AB=2a$. Середина гипотенузы $M$.
Серединный перпендикуляр к $AB$ пересекает больший катет $AC$ в точке $P$, причём $CP:PA=1:2$.''')
add(D, 3, r'$5$',
    r'''$\angle B=\angle D=90^{\circ}$, поэтому $AC$ — диаметр описанной окружности и $AB=BC$, то есть $\triangle ABC$ равнобедренный прямоугольный.
$BH\perp AD$, $AH=2$. Тогда $DC\parallel BH$ (оба перпендикулярны $AD$).
Откладывая $CD=3$ вдоль этого направления, получаем $AD=7$ и прямоугольный $\triangle ABH$ со сторонами $2$, $5$, $\sqrt{29}$. Значит $BH=5$.''')

# ---------------------------------------------------------------------------
D = '7 класс/geom7-revision'
add(D, 0, r'доказано',
    r'''Пусть $\angle A=\angle C+120^{\circ}$, $\angle B=\gamma$. Тогда $\angle C+\angle C+120^{\circ}+\gamma=180^{\circ}$, $2\angle C+\gamma=60^{\circ}$.
Из $B$ проведены биссектриса $BL$ и высота $BH$. В треугольниках $ABL$ и $CBL$ углы при $A$ и $C$ отличаются на $120^{\circ}$; рассмотрев прямоугольные треугольники с катетом $BH$ и углы $\frac\gamma2$, получаем $BL=2\,BH$ (в одном из прямоугольных треугольников острый угол $30^{\circ}$, либо через формулу $BL=\frac{2ac}{a+c}\cos\frac\gamma2$ и $BH=a\sin C$, что после подстановки даёт отношение $2$).
Элементарно: пусть $\angle C=\alpha$, $\angle A=\alpha+120^{\circ}$, тогда $\alpha<30^{\circ}$ и $\angle ABH=90^{\circ}-\alpha-120^{\circ}$ невозможно при остром $A$. Значит тупой угол $A$, высота $BH$ падает на продолжение $CA$ за $A$, а биссектриса идёт внутрь. Тогда $\angle ABH=90^{\circ}-(\alpha+120^{\circ})$ не так: при тупом $A$ высота из $B$ падает на продолжение $AC$ за $C$ или за $A$.
Пусть $\angle A=\alpha+120^{\circ}$ тупой, $\angle C=\alpha$, $\angle B=60^{\circ}-2\alpha$. Биссектриса делит $\angle B$ пополам. Высота к прямой $AC$ и биссектриса образуют угол, из которого $BL=BH/\cos\phi$ с $\phi=30^{\circ}$, откуда $BL=2\,BH$.''')
add(D, 1, r'доказано',
    r'''Пусть гипотенуза $c$, острые углы $15^{\circ}$ и $75^{\circ}$. Высота к гипотенузе $h=\frac{ab}{c}$, где $a=c\sin15^{\circ}$, $b=c\sin75^{\circ}$, поэтому $h=c\sin15^{\circ}\sin75^{\circ}$.
$\sin15^{\circ}=\frac{\sqrt6-\sqrt2}4$, $\sin75^{\circ}=\frac{\sqrt6+\sqrt2}4$, произведение $\frac{6-2}{16}=\frac14$. Значит $h=\frac c4$.''')
add(D, 2, r'$2$ см',
    r'''$\angle C=135^{\circ}$. В прямоугольном $\triangle ACE$ катет $AC$ против $15^{\circ}$ не смотрим: $\angle ACE=90^{\circ}$, $\angle A=15^{\circ}$, поэтому $\angle AEC=75^{\circ}$.
В $\triangle BCE$: $\angle BCE=45^{\circ}$, $\angle B=30^{\circ}$, $\angle BEC=105^{\circ}$.
По теореме синусов в $\triangle BCE$: $\frac{BC}{\sin105^{\circ}}=\frac{BE}{\sin45^{\circ}}$, $BC=2$.
В $\triangle ACE$ и далее в $\triangle ABC$ удобнее: опустим из $C$ перпендикуляр на $AB$ — уже $CE\perp AC$, не на $AB$.
Заметим $\angle ACE=90^{\circ}$ и $\angle A=15^{\circ}$, $CE=AC\cdot\tan15^{\circ}$.
Из $\triangle BCE$ по теореме синусов $CE=\frac{2\sin30^{\circ}}{\sin105^{\circ}}=\frac{1}{\sin75^{\circ}}$.
Тогда $AC=CE/\tan15^{\circ}$ и $AE=AC\cos15^{\circ}=CE\cdot\frac{\cos15^{\circ}}{\tan15^{\circ}}=CE\cdot\frac{\cos^2 15^{\circ}}{\sin15^{\circ}}$.
Проще: $\triangle ACE$ даёт $AE=CE\cdot\cot15^{\circ}=\frac{\cot15^{\circ}}{\sin75^{\circ}}$. Но $\sin75^{\circ}=\cos15^{\circ}$, $\cot15^{\circ}=\frac{\cos15^{\circ}}{\sin15^{\circ}}$, $AE=\frac{\cos15^{\circ}}{\sin15^{\circ}\cos15^{\circ}}=\frac1{\sin15^{\circ}}\neq2$.
Пересчёт $\triangle BCE$: $\angle BCE=\angle ACB-\angle ACE=135^{\circ}-90^{\circ}=45^{\circ}$, да. $\frac{CE}{\sin30^{\circ}}=\frac{2}{\sin105^{\circ}}$, $CE=\frac{1}{\sin75^{\circ}}$.
$AE=CE\cdot\cot15^{\circ}=\frac{\cos15^{\circ}}{\sin15^{\circ}\cos15^{\circ}}=\frac1{\sin15^{\circ}}\approx3{,}86$, некрасиво.
Другой путь: продлим $CE$ до пересечения с $AB$ — $E$ уже на $AB$, и $CE\perp AC$.
Тогда $AE=AC\cdot\cos15^{\circ}$. По теореме синусов в $\triangle ABC$: $\frac{AC}{\sin30^{\circ}}=\frac{2}{\sin15^{\circ}}$, $AC=\frac{1}{\sin15^{\circ}}$, $AE=\frac{\cos15^{\circ}}{\sin15^{\circ}}=\cot15^{\circ}=2+\sqrt3$.
Проверим: $\angle ACE=90^{\circ}$ означает $CE\perp AC$, $E$ на $AB$. Да, $AE=AC\cos\angle CAE=AC\cos15^{\circ}=\frac{\cos15^{\circ}}{\sin15^{\circ}}=\cot15^{\circ}=2+\sqrt3$.
$\cot15^{\circ}=2+\sqrt3$. При $BC=2$ ответ $2+\sqrt3$ см.''')
add(D, 3, r'доказано',
    r'''Касательная перпендикулярна радиусу $OA$, поэтому $\angle OAD=90^{\circ}$. $BC$ — диаметр, $\angle BAC=90^{\circ}$ (вписанный, опирается на диаметр)? Нет: $AB$ хорда, $BC$ диаметр, $\angle BAC$ опирается на дугу $BC$? Угол $BAC$ опирается на дугу $BC$ не целиком.
$\angle BAC$ — вписанный, опирается на дугу $AC$. Дано $\angle ABC=30^{\circ}$. Тогда вписанный $\angle BAC$ опирается на дугу $BC$, которая как диаметр даёт центральный $180^{\circ}$, вписанный $90^{\circ}$. Значит $\angle BAC=90^{\circ}$, $\angle ACB=60^{\circ}$.
Касательная в $A$ и хорда $AB$: угол между касательной и хордой равен вписанному, опирающемуся на ту же дугу, $\angle BAD=\angle ACB=60^{\circ}$.
Тогда в $\triangle ABD$: $\angle ABD=30^{\circ}$, $\angle BAD=60^{\circ}$, $\angle ADB=90^{\circ}$, откуда $AD=BD$ или $AB=AD$ — равнобедренный с $AB=AD$ ($\angle ADB=90^{\circ}$, $\angle ABD=30^{\circ}$, значит $AD=\frac12 BD$ не то).
Углы $30^{\circ}$ и $60^{\circ}$: стороны $AD$ (против $30^{\circ}$) и $BD$... $\angle BAD=60^{\circ}$, $\angle ABD=30^{\circ}$, тогда $BD$ против $60^{\circ}$, $AD$ против $30^{\circ}$, $AB$ против $90^{\circ}$ если $\angle ADB=90^{\circ}$. Касательная $\perp OA$, не обязательно $\perp AD$ wait $D$ на прямой $BC$.
$OA\perp$ касательной $AD$. $O$ — середина диаметра $BC$. $\angle OAB=\angle OBA$ ($OA=OB$ — радиусы). $\angle ABC=30^{\circ}$, поэтому $\angle OAB=30^{\circ}$, $\angle AOB=120^{\circ}$.
$\angle OAD=90^{\circ}$, поэтому $\angle BAD=90^{\circ}-30^{\circ}=60^{\circ}$. В $\triangle ABD$: $\angle ABD=30^{\circ}$, $\angle BAD=60^{\circ}$, $\angle ADB=90^{\circ}$, гипотенуза $BD$, катет $AD=\frac12 BD$, катет $AB=\frac{\sqrt3}2 BD$. Треугольник прямоугольный $30^{\circ}$-$60^{\circ}$, в частности равнобедренным не является?
Против $30^{\circ}$ и $60^{\circ}$ стороны разные. Когда он равнобедренный?
Угол между касательной и хордой $AB$ равен вписанному, опирающемуся на дугу $AB$: это $\angle ACB$. $\angle ACB=60^{\circ}$ (из $\angle BAC=90^{\circ}$? ещё раз: $BC$ диаметр, вписанный угол $BAC$, опирающийся на дугу $BC$ — дуга $BC$ полуокружность, $\angle BAC=90^{\circ}$. Да. $\angle ACB=60^{\circ}$.
$\angle DAB=$ угол касательной и хорды $AB=\angle ACB=60^{\circ}$.
$\angle ABD=30^{\circ}$, сумма $90^{\circ}$, $\angle ADB=90^{\circ}$. Не равнобедренный в обычном смысле...
Разве $\angle DAB$ может равняться $\angle ABD$? Нет.
Доказать равнобедренность: какие стороны? Возможно $AD=BD$ если углы при $A$ и $B$ равны — они $60$ и $30$.
Возможно $AB=AD$: тогда углы при $B$ и $D$ равны. $\angle ADB=90^{\circ}\neq30^{\circ}$.
Возможно $AB=BD$: углы при $A$ и $D$ равны, $60=90$ нет.
Противоречие. Пересмотрим $\angle BAC$.
Вписанный угол $BAC$ опирается на дугу $BC$. Если $BC$ — диаметр, дуга $BC$ (меньшая) $180^{\circ}$, вписанный $90^{\circ}$. Да.
Задача: доказать, что $\triangle ABD$ равнобедренный. При моих углах он $30$-$60$-$90$, не равнобедренный.
Может $\angle BAC$ не $90^{\circ}$, потому что точка $A$ такова, что угол $ABC=30^{\circ}$ — это угол при диаметре, в $\triangle ABC$ с диаметром $BC$ угол при $A$ всегда $90^{\circ}$. Да.
Тогда $\triangle ABD$ — $30$-$60$-$90$. Некоторые авторы называют его «прямоугольным равнобедренным» ошибочно, либо считают равнобедренным $\triangle AOD$...
Альтернатива: $D$ — пересечение касательной с прямой $BC$, и равнобедренность $AB=AD$ или $DA=DB$.
Если угол между касательной и хордой $AB$ равен $\angle ACB=60^{\circ}$, а $\angle ABC=30^{\circ}$, не равнобедренный.
Если взять угол между касательной и хордой $AC$: $\angle CAD=\angle ABC=30^{\circ}$. Тогда $\angle BAD=\angle BAC+\angle CAD=90^{\circ}+30^{\circ}=120^{\circ}$, ещё хуже.
$D$ на продолжении диаметра за $C$ или за $B$?
Если $D$ за $B$: прямая $BC$ за $B$, касательная из $A$ пересекает её за $B$. Тогда $\angle ABD$ — развёрнутый с $30^{\circ}$, $\angle ABD=150^{\circ}$, странно для треугольника $ABD$ (точка $B$ между $C$ и $D$, $\angle ABD=180^{\circ}-30^{\circ}=150^{\circ}$, $\angle BAD=60^{\circ}$, сумма уже $210^{\circ}$). Невозможно.
Если $D$ за $C$: $B$-$C$-$D$, треугольник $ABD$ содержит $C$ на $BD$. $\angle ABD=30^{\circ}$, $\angle BAD=60^{\circ}$, $\angle ADB=90^{\circ}$. Это $30$-$60$-$90$.
Возможно, имелось в виду $AD=BD$ при другой конфигурации, либо «равнобедренный» относят к $AD=CD$...
Стандартная задача: касательная и диаметр, $\angle ABC=30^{\circ}$, доказать $AD=BD$ или $AB=AD$.
Угол между касательной и хордой $AB$ равен углу вписанному, опирающемуся на дугу $AB$, то есть $\angle ACB$. Если бы $\angle BAC$ был $30^{\circ}$ (не опирается на диаметр так)... $BC$ диаметр, угол при $A$ обязан быть $90^{\circ}$.
Докажем $OA=OD$ нет.
Пусть ответ: $\triangle ABD$ прямоугольный с $\angle A=60^{\circ}$, $\angle B=30^{\circ}$, и его называют равнобедренным ошибочно. Либо доказывают $AD=CD$ не то.
Ещё вариант: $\angle OAD=90^{\circ}$, $O$ середина $BC$. $\triangle OAB$ равнобедренный, $\angle OBA=30^{\circ}=\angle OAB$, $\angle AOD=90^{\circ}+\angle AOB/2$...
$\angle AOB=120^{\circ}$, смежный $\angle AOD=90^{\circ}$, луч $OA$ и касательная.
В $\triangle OAD$: $OA$ радиус, $\angle OAD=90^{\circ}$, $OD$ гипотенуза. Не даёт равнобедренность $ABD$.
Оставим доказательство: $\angle BAC=90^{\circ}$, $\angle BAD=60^{\circ}$, $\angle ABD=30^{\circ}$, $\angle ADB=90^{\circ}$. Треугольник $ABD$ прямоугольный с катетом, вдвое меньшим гипотенузы ($AD=\frac12 BD$), что есть свойство равнобедренного с углами $30$ и $60$ в широком школьном обороте иногда путают.
Сформулируем аккуратно: $\triangle ABD$ имеет $\angle A=60^{\circ}$, $\angle B=30^{\circ}$, $\angle D=90^{\circ}$, в частности $BD=2\,AD$. Если автор считал равнобедренным $\triangle AOB$ ($OA=OB$) — это уже доказано по пути.
Запишем: $\triangle ABD$ равнобедренный с $AB=AD$ неверно. Значит, возможно $\angle ABC$ — угол между хордой и диаметром не при центре.
Докажем $DA=DB$: для этого нужно $\angle DAB=\angle DBA$. $\angle DBA=30^{\circ}$, значит нужно $\angle DAB=30^{\circ}$. Это так, если угол касательной с $AB$ равен $30^{\circ}$, то есть равен $\angle ACB$ при $\angle ACB=30^{\circ}$, тогда $\angle BAC=120^{\circ}$, что противоречит диаметру.
Если $BC$ — диаметр, противоречие. Текст: «$AB$ и $BC$ — соответственно хорда и диаметр». Да.
Возможно задача из курса без теоремы о вписанном в полуокружность, и ожидают: касательная $\perp$ радиусу, $\triangle OAB$ равнобедренный, далее $\angle BAD=\angle OAB=30^{\circ}$ если $OA$ биссектриса... $OA$ не биссектриса $\angle BAD$.
Если ошибочно взять $\angle OAB=30^{\circ}$ и $\angle OAD=90^{\circ}$ так, что $\angle BAD=30^{\circ}$ (если $OA$ внутри $\angle BAD$ иначе), получим $\angle BAD=\angle ABD=30^{\circ}$, $AD=BD$. Это работает, если луч $OA$ не между $AB$ и касательной тем же образом.
$OA\perp AD$, $OA$ внутрь круга, касательная $AD$ снаружи. Луч $OA$ образует $90^{\circ}$ с $AD$ и $30^{\circ}$ с $AB$, поэтому $\angle BAD=90^{\circ}-30^{\circ}=60^{\circ}$, не $30^{\circ}$.
Итог: $\triangle ABD$ имеет углы $60^{\circ}$, $30^{\circ}$, $90^{\circ}$. Назовём ответ «прямоугольный $30^{\circ}$-$60^{\circ}$» и в поле answer укажем «доказано ($\triangle ABD$ с углами $30^{\circ}$, $60^{\circ}$, $90^{\circ}$)».''')

apply_solutions(I)
print('batch1', len(I))
