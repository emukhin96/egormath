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

D = '6 класс/promatvert/math6-06а-finding_part_and_whole'

add(D, 1,
    r'$6$; $14$; $7$; $\dfrac{30}{77}$; $77$',
    r'Часть от целого — произведение. '
    r'$1\frac{1}{2}\cdot 4=6$; '
    r'$2\frac{1}{3}\cdot 6=14$; '
    r'$4\frac{2}{3}\cdot 1\frac{1}{2}=\frac{14}{3}\cdot\frac{3}{2}=7$; '
    r'$\frac{6}{7}\cdot\frac{5}{11}=\frac{30}{77}$; '
    r'$12\frac{1}{4}\cdot 6\frac{2}{7}=\frac{49}{4}\cdot\frac{44}{7}=77$.')

add(D, 2,
    r'$\dfrac{40}{77}$; $\dfrac{40}{77}$; равны, умножение коммутативно',
    r'$\frac{5}{7}$ от $\frac{8}{11}$ целого: $\frac{5}{7}\cdot\frac{8}{11}=\frac{40}{77}$. '
    r'$\frac{8}{11}$ от $\frac{5}{7}$ целого: $\frac{8}{11}\cdot\frac{5}{7}=\frac{40}{77}$. '
    r'Ответы равны, потому что умножение дробей перестановочно.')

add(D, 3,
    r'$\dfrac{8}{3}$; $\dfrac{12}{11}$; $4$; $3$; $\dfrac{7}{6}$; $\dfrac{7}{6}$',
    r'Целое равно данной величине, делённой на указанную часть. '
    r'$1\frac{1}{3}:\frac{1}{2}=\frac{8}{3}$; '
    r'$\frac{8}{11}:\frac{2}{3}=\frac{12}{11}$; '
    r'$6:1\frac{1}{2}=4$; '
    r'$11:3\frac{2}{3}=3$; '
    r'$5\frac{1}{2}:4\frac{5}{7}=\frac{11}{2}\cdot\frac{7}{33}=\frac{7}{6}$; '
    r'$6\frac{2}{3}:5\frac{5}{7}=\frac{20}{3}\cdot\frac{7}{40}=\frac{7}{6}$.')

add(D, 4,
    r'$\dfrac{15}{19}$; $5$; $\dfrac{1}{3}$; $\dfrac{3}{4}$; $7$; $\dfrac{1}{7}$',
    r'Отношение первого ко второму: '
    r'$\frac{30}{38}=\frac{15}{19}$; $\frac{75}{15}=5$; '
    r'$\frac{1/6}{1/2}=\frac{1}{3}$; '
    r'$\frac{5/2}{10/3}=\frac{3}{4}$; '
    r'$5:\frac{5}{7}=7$; $\frac{5}{7}:5=\frac{1}{7}$.')

add(D, 5,
    r'$8300$; $5$; $123\dfrac{57}{58}$; $10$; $47$',
    r'Вынести общий множитель. '
    r'$83(57+43)=8300$; '
    r'$2\frac{1}{2}\bigl(1\frac{1}{7}+\frac{6}{7}\bigr)=2\frac{1}{2}\cdot 2=5$; '
    r'$123\frac{57}{58}\bigl(\frac{1}{2}+\frac{1}{3}+\frac{1}{6}\bigr)=123\frac{57}{58}$; '
    r'$3\frac{1}{3}\bigl(\frac{5}{6}+\frac{7}{8}+1\frac{7}{24}\bigr)=3\frac{1}{3}\cdot 3=10$; '
    r'$47(47-46)=47$.')

add(D, 6,
    r'$6$ мин',
    r'Первый насос $5/2$ л/мин, второй $5/3$ л/мин. Вместе $\frac{25}{6}$ л/мин. '
    r'На $25$ л нужно $25:\frac{25}{6}=6$ мин.')

apply_solutions(I)
