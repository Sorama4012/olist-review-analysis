"""Собирает analysis.ipynb из ячеек ниже (потом выполняется через nbconvert)."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Olist: как доставка влияет на оценку отзыва

**Вопрос:** почему клиенты бразильского маркетплейса Olist ставят плохие оценки, и насколько в этом виновата доставка?

План ноутбука:
1. Загрузка данных.
2. Проверка данных: пропуски, дубликаты, логические несоответствия в датах — и что я с ними сделал.
3. Связь опоздания (в днях) и средней оценки.
4. Три главные находки в графиках.
5. Выводы.

Агрегаты для SQL-части лежат в `queries.sql`, здесь те же метрики считаются в pandas — цифры совпадают.
""")

code("""
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd

DATA = Path("data")
IMG = Path("images")
IMG.mkdir(exist_ok=True)

# Палитра: синий — «вовремя / база», оранжевый — «опоздание / проблема»
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"
plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#b5b4ae", "axes.grid": True, "grid.color": "#e6e5e0",
    "grid.linewidth": 0.8, "axes.axisbelow": True, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
})
pd.set_option("display.float_format", "{:,.2f}".format)
""")

code("""
date_cols = ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
             "order_delivered_customer_date", "order_estimated_delivery_date"]
orders    = pd.read_csv(DATA / "olist_orders_dataset.csv", parse_dates=date_cols)
items     = pd.read_csv(DATA / "olist_order_items_dataset.csv")
reviews   = pd.read_csv(DATA / "olist_order_reviews_dataset.csv",
                        parse_dates=["review_creation_date", "review_answer_timestamp"])
products  = pd.read_csv(DATA / "olist_products_dataset.csv")
customers = pd.read_csv(DATA / "olist_customers_dataset.csv")
sellers   = pd.read_csv(DATA / "olist_sellers_dataset.csv")
cat_en    = pd.read_csv(DATA / "product_category_name_translation.csv")

tables = dict(orders=orders, items=items, reviews=reviews, products=products,
              customers=customers, sellers=sellers)
pd.DataFrame({name: [len(df), df.shape[1]] for name, df in tables.items()},
             index=["строк", "столбцов"]).T
""")

md("""
## 1. Проверка данных

Проверяю три вещи: пропуски, дубликаты и логику дат (доставка не может быть раньше покупки, передача перевозчику — раньше оплаты и т.д.).
""")

md("### 1.1 Пропуски")

code("""
na = pd.concat({name: df.isna().sum() for name, df in tables.items()})
na = na[na > 0].rename("пропусков").to_frame()
na["доля, %"] = [100 * v / len(tables[t]) for (t, _), v in na["пропусков"].items()]
na
""")

code("""
# Пропуски в датах доставки — это нормально для недоставленных заказов? Проверяем по статусам.
pd.crosstab(orders["order_status"], orders["order_delivered_customer_date"].isna(),
            margins=True).rename(columns={False: "дата есть", True: "даты нет"})
""")

md("### 1.2 Дубликаты")

code("""
multi_review = reviews.groupby("order_id").size()
shared_review_id = reviews.drop_duplicates(["review_id", "order_id"])["review_id"].duplicated()

pd.Series({
    "дубли order_id в orders":                    orders["order_id"].duplicated().sum(),
    "полные дубли строк в reviews":               reviews.duplicated().sum(),
    "полные дубли строк в items":                 items.duplicated().sum(),
    "заказов с >1 отзывом":                       (multi_review > 1).sum(),
    "review_id, привязанный к нескольким заказам": shared_review_id.sum(),
    "заказов без отзыва":                         (~orders["order_id"].isin(reviews["order_id"])).sum(),
}, name="количество").to_frame()
""")

md("### 1.3 Несоответствия в датах")

code("""
o = orders
checks = {
    "доставка клиенту раньше покупки":   o["order_delivered_customer_date"] < o["order_purchase_timestamp"],
    "оплата одобрена раньше покупки":    o["order_approved_at"] < o["order_purchase_timestamp"],
    "передача перевозчику раньше покупки": o["order_delivered_carrier_date"] < o["order_purchase_timestamp"],
    "доставка клиенту раньше передачи перевозчику": o["order_delivered_customer_date"] < o["order_delivered_carrier_date"],
    "статус delivered, но даты доставки нет": (o["order_status"] == "delivered") & o["order_delivered_customer_date"].isna(),
    "статус не delivered, но дата доставки есть": (o["order_status"] != "delivered") & o["order_delivered_customer_date"].notna(),
}
purchase_by_order = o.set_index("order_id")["order_purchase_timestamp"].dt.normalize()
checks_reviews = reviews["review_creation_date"] < reviews["order_id"].map(purchase_by_order)

issues = pd.Series({k: v.sum() for k, v in checks.items()}, name="заказов").to_frame()
issues.loc["отзыв создан раньше дня покупки"] = checks_reviews.sum()
issues
""")

code("""
# Пример: заказы, переданные перевозчику раньше, чем были куплены
o.loc[checks["передача перевозчику раньше покупки"],
      ["order_id", "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date"]].head()
""")

md("""
### 1.4 Что нашёл в данных и что с этим сделал

| Находка | Масштаб | Решение |
|---|---|---|
| Пропуски в датах доставки | ~3% заказов, почти все — недоставленные статусы (shipped, canceled, unavailable…) | Это не ошибка, а состояние заказа. В анализ доставки беру только `delivered` с заполненной датой |
| `delivered` без даты доставки | 8 заказов | Исключил из анализа сроков: нельзя посчитать опоздание |
| `canceled`, но с датой доставки | 6 заказов | Исключил: статус противоречит факту, верить нельзя ни тому, ни другому |
| Доставка раньше покупки | **0** | Проверка пройдена — грубых ошибок в ключевой дате нет |
| Передача перевозчику раньше покупки | 166 заказов | Ошибка учёта на стороне продавца/логистики. На метрику опоздания не влияет (она считается по дате доставки клиенту), поэтому заказы оставил, но этой датой не пользуюсь |
| Доставка клиенту раньше передачи перевозчику | 23 заказа | Аналогично: дата передачи перевозчику ненадёжна, в метриках её не использую |
| Отзыв создан раньше дня покупки | 64 отзыва | Мало, на средние не влияет. Оставил, отметил как известную аномалию |
| Несколько отзывов на один заказ | 547 заказов | Усредняю оценку до уровня заказа, иначе такие заказы весят в 2–3 раза больше |
| Один `review_id` на несколько заказов | 814 случаев | Похоже, клиент оставил один отзыв на покупку, разбитую на несколько заказов. Оставил: для каждого заказа это его реальная оценка |
| Товары без категории | 610 товаров | Помечаю как `unknown`, не выбрасываю — иначе теряется выручка |
| Пропуски в тексте отзыва | 59–88% | Норма: текст необязателен. Работаю только с оценкой |

**Итог:** данные в целом чистые; главное — правильно выбрать знаменатель (только доставленные заказы с датой) и не задвоить оценки.
""")

code("""
# Чистый набор для анализа доставки: один заказ = одна строка, одна (средняя) оценка
order_score = reviews.groupby("order_id")["review_score"].mean().rename("score")

d = orders[(orders["order_status"] == "delivered") & orders["order_delivered_customer_date"].notna()].copy()
d = d.join(order_score, on="order_id", how="inner")
d = d.merge(customers[["customer_id", "customer_state"]], on="customer_id")

# Опоздание в днях: положительное — опоздали, отрицательное — привезли раньше обещанного
d["delay_days"] = (d["order_delivered_customer_date"].dt.normalize() - d["order_estimated_delivery_date"]).dt.days
d["is_late"] = d["delay_days"] > 0
d["bad"] = d["score"] <= 2
d["month"] = d["order_purchase_timestamp"].dt.to_period("M")
print(f"Заказов в анализе: {len(d):,}; опоздали: {d['is_late'].mean():.1%}")
""")

md("""
## 2. Опоздание и оценка

Главный вопрос: как меняется средняя оценка с каждым днём опоздания. Беру диапазон от −30 до +30 дней и показываю только точки, где хотя бы 30 заказов, чтобы хвосты не шумели.
""")

code("""
by_delay = d.groupby("delay_days").agg(orders=("score", "size"), avg_score=("score", "mean"))
curve = by_delay[(by_delay.index.to_series().between(-30, 30)) & (by_delay["orders"] >= 30)]

fig, ax = plt.subplots(figsize=(9, 4.2))
early, late = curve[curve.index <= 0], curve[curve.index >= 0]
ax.plot(early.index, early["avg_score"], color=BLUE, lw=2, marker="o", ms=4, label="вовремя / раньше срока")
ax.plot(late.index, late["avg_score"], color=ORANGE, lw=2, marker="o", ms=4, label="с опозданием")
ax.axvline(0, color=GRAY, lw=1, ls="--")
ax.text(0.4, 1.25, "обещанная дата", color="#52514e", fontsize=9)
ax.set(xlabel="дней относительно обещанной даты (− раньше, + позже)", ylabel="средняя оценка",
       ylim=(1, 5), title="После обещанной даты оценка обваливается: +3 дня — 2,7, неделя опоздания — ниже 2")
ax.legend(frameon=False, loc="lower left")
fig.savefig(IMG / "01_delay_vs_score.png")
plt.show()

curve.loc[[-10, -5, 0, 1, 2, 3, 5, 7, 10, 14, 20]].round(2)
""")

md("""
Кривая почти плоская слева от нуля: привезти на 5 или на 20 дней раньше — для клиента одно и то же (≈4,3). Обвал начинается ровно с даты обещания: +1 день — 3,7, **+3 дня — уже 2,7** (минус 1,6 балла к «вовремя»), а после недели опоздания средняя оценка опускается до 1,6–1,9. Значит, клиент оценивает не скорость доставки, а **выполнение обещания**.
""")

md("## 3. Главные находки")
md("### 3.1 Вовремя vs с опозданием: опоздание превращает отзыв в жалобу")

code("""
summary = d.groupby("is_late").agg(orders=("score", "size"), avg_score=("score", "mean"),
                                   bad_pct=("bad", "mean")).rename(index={False: "вовремя", True: "с опозданием"})
summary["bad_pct"] *= 100
display(summary.round(2))

# Распределение оценок 1–5 в каждой группе
dist = (pd.crosstab(d["is_late"], d["score"].round().astype(int), normalize="index") * 100
        ).rename(index={False: "вовремя", True: "с опозданием"})

fig, ax = plt.subplots(figsize=(9, 4))
x = range(1, 6)
w = 0.38
ax.bar([i - w / 2 for i in x], dist.loc["вовремя"], width=w - 0.02, color=BLUE, label="вовремя")
ax.bar([i + w / 2 for i in x], dist.loc["с опозданием"], width=w - 0.02, color=ORANGE, label="с опозданием")
for i in x:
    for shift, grp in ((-w / 2, "вовремя"), (w / 2, "с опозданием")):
        ax.text(i + shift, dist.loc[grp, i] + 1, f"{dist.loc[grp, i]:.0f}%", ha="center", fontsize=8, color="#52514e")
ax.set_xticks(list(x), [f"{i} ★" for i in x])
ax.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
ax.set(ylabel="доля заказов группы", title=f"При опоздании больше половины оценок — единица "
       f"(средняя {summary.loc['с опозданием', 'avg_score']:.2f} против {summary.loc['вовремя', 'avg_score']:.2f})")
ax.legend(frameon=False)
fig.savefig(IMG / "02_score_distribution.png")
plt.show()
""")

md("""
Заказы, доставленные с опозданием, — это ~7% всех доставок, но среди них **более 60% оценок 1–2** против ~9% у доставленных вовремя. Распределение «переворачивается»: у вовремя доставленных мода — 5 звёзд, у опоздавших — 1 звезда.
""")

md("### 3.2 Опоздания по месяцам: провалы после пиков спроса")

code("""
monthly = d.groupby("month").agg(orders=("score", "size"), late_pct=("is_late", "mean"),
                                 avg_score=("score", "mean"))
monthly = monthly[monthly["orders"] >= 500]  # отрезаем неполные месяцы на краях
monthly["late_pct"] *= 100

fig, axes = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True, gridspec_kw={"hspace": 0.25})
idx = monthly.index.astype(str)
axes[0].plot(idx, monthly["late_pct"], color=ORANGE, lw=2, marker="o", ms=4)
axes[0].yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
axes[0].set(ylabel="доля опозданий", title="Доля опозданий растёт — оценка падает в те же месяцы")
axes[1].plot(idx, monthly["avg_score"], color=BLUE, lw=2, marker="o", ms=4)
axes[1].set(ylabel="средняя оценка")
for ax in axes:
    for m in ("2017-11", "2018-03"):
        ax.axvline(m, color=GRAY, lw=1, ls="--")
axes[0].text("2017-11", monthly["late_pct"].max() * 0.95, " Black Friday", fontsize=8, color="#52514e")
axes[0].text("2018-03", monthly["late_pct"].max() * 0.95, " февраль–март 2018", fontsize=8, color="#52514e")
axes[1].tick_params(axis="x", rotation=45)
fig.savefig(IMG / "03_monthly_late_vs_score.png")
plt.show()

print("Корреляция доли опозданий и средней оценки по месяцам:",
      round(monthly["late_pct"].corr(monthly["avg_score"]), 2))
monthly.round(2).T
""")

md("""
Две вспышки опозданий — ноябрь 2017 (Black Friday) и февраль–март 2018 — и в обоих случаях средняя оценка месяца проседает. Помесячно доля опозданий и средняя оценка связаны почти линейно (корреляция около −0,9). Логистика не масштабируется под пиковый спрос, и это сразу бьёт по репутации.
""")

md("### 3.3 География: опоздания концентрируются на северо-востоке")

code("""
states = d.groupby("customer_state").agg(orders=("score", "size"), late_pct=("is_late", "mean"),
                                         avg_score=("score", "mean"))
states["late_pct"] *= 100
states = states[states["orders"] >= 100].sort_values("late_pct")
overall = d["is_late"].mean() * 100

fig, ax = plt.subplots(figsize=(9, 6))
colors = [ORANGE if v > overall * 1.5 else BLUE for v in states["late_pct"]]
ax.barh(states.index, states["late_pct"], color=colors, height=0.7)
ax.axvline(overall, color=GRAY, lw=1, ls="--")
ax.text(overall + 0.2, -0.9, f"в среднем {overall:.1f}%", fontsize=8, color="#52514e")
for i, (v, s) in enumerate(zip(states["late_pct"], states["avg_score"])):
    ax.text(v + 0.2, i, f"{v:.1f}%  ·  ★ {s:.2f}", va="center", fontsize=8, color="#52514e")
ax.xaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
ax.set(xlabel="доля заказов с опозданием", xlim=(0, states["late_pct"].max() * 1.3),
       title="В AL и MA опаздывает каждый 5–6-й заказ — в 4–5 раз чаще, чем в SP")
ax.grid(axis="y", visible=False)
fig.savefig(IMG / "04_late_by_state.png")
plt.show()
""")

md("""
Оранжевым выделены штаты, где опаздывают в 1,5+ раза чаще среднего (>10%). Лидеры — Алагоас (AL), Мараньян (MA), Сержипи (SE), Пиауи (PI), Сеара (CE): северо-восток, далеко от продавцов, которые в основном сидят в Сан-Паулу. Отдельно выделяется Рио (RJ): 12% опозданий при огромном объёме заказов. (Цифры чуть отличаются от запроса 4 в SQL: здесь в знаменателе только заказы с отзывом.) Подпись справа показывает среднюю оценку: чем больше опозданий, тем ниже звёзды. Обещанный срок для этих штатов занижен относительно реальной логистики.
""")

md("""
## 4. Выводы

1. **Опоздание — главный драйвер плохих отзывов.** Средняя оценка: ~4,3 вовремя против ~2,3 с опозданием; доля оценок 1–2 растёт с ~9% до ~62%.
2. **Важна не скорость, а обещание.** Приехать на 20 дней раньше даёт ту же оценку, что и на 5 дней раньше; а уже 3 дня опоздания снижают её с ~4,3 до 2,7.
3. **Опоздания сезонны.** Пики в ноябре 2017 и феврале–марте 2018 совпадают с провалами средней оценки.
4. **Опоздания географичны.** Северо-восток (AL, MA, SE, PI, CE) получает опоздание в 14–21% заказов против 6,7% в среднем и 4,4% в Сан-Паулу.

**Что из этого следует для бизнеса** — в README: пересчитать обещанную дату для дальних штатов и пиковых месяцев, мониторить продавцов с высокой долей плохих отзывов и опозданий (см. запрос 6 в `queries.sql` и VBA-письмо в `report.xlsm`).
""")

nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "analysis.ipynb")
print("analysis.ipynb written")
