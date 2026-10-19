"""Собирает report.xlsm: выгрузка агрегатов из SQL -> сводные со срезами -> дашборд -> VBA-кнопка.

Нужен установленный Excel (Windows) и pywin32. Шаги:
  1. openpyxl пишет данные (факт-таблица, продавцы, листы-заготовки);
  2. Excel через COM строит сводные, срезы, диаграммы и сохраняет .xlsm;
  3. модуль vba/QualityLetter.bas импортируется, если в Excel включён
     «Доверять доступ к объектной модели проектов VBA»; иначе его нужно
     импортировать вручную (Alt+F11 -> File -> Import File).
"""
import sqlite3
from pathlib import Path

import pandas as pd
import win32com.client as win32
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).parent.resolve()
XLSX_TMP = ROOT / "_report_tmp.xlsx"
XLSM = ROOT / "report.xlsm"
BAS = ROOT / "vba" / "QualityLetter.bas"

BLUE, ORANGE, INK, MUTED, SURFACE = "2A78D6", "EB6834", "0B0B0B", "52514E", "F4F3EF"


def rgb(hex_):  # Excel COM ждёт BGR
    r, g, b = int(hex_[0:2], 16), int(hex_[2:4], 16), int(hex_[4:6], 16)
    return r + g * 256 + b * 65536


# ---------------------------------------------------------------- 1. SQL
sql = (ROOT / "queries.sql").read_text(encoding="utf-8")
exports = {s.split("@export:")[1].split()[0]: s for s in sql.split(";") if "@export:" in s}
with sqlite3.connect(ROOT / "olist.db") as con:
    facts = pd.read_sql(exports["facts"], con)
    sellers = pd.read_sql(exports["sellers"], con)

platform_bad = facts["bad_w"].sum() / facts["reviewed_w"].sum()
platform_late = facts["late_w"].sum() / facts["orders_w"].sum()

# ---------------------------------------------------------------- 2. openpyxl
wb = Workbook()
dash = wb.active
dash.title = "Дашборд"
wb.create_sheet("Сводные")
ws_s = wb.create_sheet("Продавцы")
ws_l = wb.create_sheet("Письмо")
ws_d = wb.create_sheet("Данные")
ws_i = wb.create_sheet("Справка")

ws_d.append(list(facts.columns))
for row in facts.itertuples(index=False):
    ws_d.append(list(row))

# Продавцы: панель управления + таблица
title_font = Font(size=16, bold=True, color=INK)
ws_s["A1"] = "Письмо-уведомление продавцу о качестве"
ws_s["A1"].font = title_font
ws_s["A3"] = "Продавец (seller_id):"
ws_s["B3"].value = sellers.loc[0, "seller_id"]
ws_s["B3"].fill = PatternFill("solid", fgColor="FFF2CC")
ws_s["A4"] = "Норма платформы: доля оценок 1–2"
ws_s["B4"] = platform_bad
ws_s["A5"] = "Норма платформы: доля опозданий"
ws_s["B5"] = platform_late
ws_s["A6"] = "Срок исправления, дней"
ws_s["B6"] = 30
ws_s["D4"] = "Подпись:"
ws_s["E4"] = "Менеджер по качеству"
for c in ("B4", "B5"):
    ws_s[c].number_format = "0.0%"
for c in ("A3", "A4", "A5", "A6", "D4"):
    ws_s[c].font = Font(color=MUTED)
ws_s["B3"].font = Font(bold=True)

HDR = 8
headers = {"seller_id": "seller_id", "seller_city": "seller_city", "seller_state": "seller_state",
           "reviewed_orders": "reviewed_orders", "revenue": "revenue", "avg_score": "avg_score",
           "bad_share": "bad_share", "late_share": "late_share", "avg_delay_days": "avg_delay_days"}
ws_s.cell(HDR - 1, 1, "Продавцы с ≥ 30 оценёнными заказами, по убыванию доли оценок 1–2. "
                      "Выберите продавца в жёлтой ячейке или скопируйте seller_id из таблицы.").font = Font(color=MUTED, italic=True)
for j, h in enumerate(headers, 1):
    ws_s.cell(HDR, j, h)
for i, row in enumerate(sellers.itertuples(index=False), HDR + 1):
    for j, v in enumerate(row, 1):
        ws_s.cell(i, j, None if pd.isna(v) else v)
last = HDR + len(sellers)
tbl = Table(displayName="tblSellers", ref=f"A{HDR}:I{last}")
tbl.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
ws_s.add_table(tbl)
for i in range(HDR + 1, last + 1):
    ws_s[f"E{i}"].number_format = "#,##0"
    ws_s[f"G{i}"].number_format = "0.0%"
    ws_s[f"H{i}"].number_format = "0.0%"
for col, w in zip("ABCDEFGHI", (36, 18, 12, 16, 12, 11, 11, 11, 15)):
    ws_s.column_dimensions[col].width = w
ws_s.freeze_panes = f"A{HDR + 1}"

dv = DataValidation(type="list", formula1=f"=$A${HDR + 1}:$A${last}", allow_blank=False)
ws_s.add_data_validation(dv)
dv.add("B3")

for name, ref in {"SelectedSeller": "$B$3", "PlatformBadShare": "$B$4",
                  "PlatformLateShare": "$B$5", "FixDays": "$B$6", "SenderName": "$E$4"}.items():
    wb.defined_names[name] = DefinedName(name, attr_text=f"'Продавцы'!{ref}")

ws_l["B1"] = "Здесь появится письмо после нажатия кнопки на листе «Продавцы»."
ws_l["B1"].font = Font(color=MUTED, italic=True)
ws_l.column_dimensions["A"].width = 3
ws_l.column_dimensions["B"].width = 120

info = [
    ("Отчёт по качеству продавцов Olist", True),
    ("", False),
    ("Источник: Brazilian E-Commerce Public Dataset by Olist (Kaggle), 2016–2018.", False),
    ("Данные: доставленные заказы с датой доставки, январь 2017 — август 2018; выгрузка запросов 8 и 9 из queries.sql.", False),
    ("", False),
    ("Как считаются метрики", True),
    ("Выручка — сумма цен товаров (без доставки).", False),
    ("Заказы — заказ с товарами из N категорий разбит на N строк с весом 1/N, поэтому сумма весов = число заказов.", False),
    ("Доля опозданий — доставлено позже обещанной даты / все доставленные.", False),
    ("Средняя оценка — по заказам с отзывом; несколько отзывов на заказ усреднены.", False),
    ("Доля оценок 1–2 — заказы с оценкой ≤ 2 / заказы с отзывом.", False),
    ("", False),
    ("Как пользоваться", True),
    ("Дашборд: срезы «Месяц», «Штат», «Категория» фильтруют все показатели и графики одновременно.", False),
    ("Продавцы: выберите seller_id в жёлтой ячейке и нажмите «Сформировать письмо».", False),
    ("Нормы платформы и срок исправления можно поменять в ячейках B4:B6 листа «Продавцы».", False),
]
for i, (text, bold) in enumerate(info, 1):
    ws_i.cell(i, 1, text).font = Font(bold=bold, size=14 if i == 1 else 11)
ws_i.column_dimensions["A"].width = 110

wb.save(XLSX_TMP)
print(f"openpyxl: {len(facts):,} строк фактов, {len(sellers)} продавцов")

# ---------------------------------------------------------------- 3. Excel COM
xl = win32.DispatchEx("Excel.Application")
xl.Visible = False
xl.DisplayAlerts = False
try:
    book = xl.Workbooks.Open(str(XLSX_TMP))
    S = book.Worksheets
    piv, dash = S("Сводные"), S("Дашборд")

    n_rows, n_cols = len(facts) + 1, len(facts.columns)
    cache = book.PivotCaches().Create(SourceType=1, SourceData=f"'Данные'!R1C1:R{n_rows}C{n_cols}", Version=6)

    xlSum, xlRow, xlDesc = -4157, 1, 2
    pts = {}

    # COM-вызовы через pywin32 принимают форматы в локали пользователя (в RU: «0,0%», «# ##0»)
    intl = xl.International
    dec_sep, thou_sep = intl[2], intl[3]

    def loc(fmt):
        return fmt.replace(",", "§").replace(".", dec_sep).replace("§", thou_sep)

    def set_fmt(target, fmt):
        target.NumberFormat = loc(fmt)

    def make_pt(name, cell, rows=None, values=()):
        pt = cache.CreatePivotTable(TableDestination=piv.Range(cell), TableName=name, DefaultVersion=6)
        pt.RowAxisLayout(1)  # табличная форма
        if rows:
            pt.PivotFields(rows).Orientation = xlRow
        for field, caption, fmt in values:
            set_fmt(pt.AddDataField(pt.PivotFields(field), caption, xlSum), fmt)
        pts[name] = pt
        return pt

    # вычисляемые поля живут в кэше — создаём один раз
    first = cache.CreatePivotTable(TableDestination=piv.Range("A3"), TableName="PT_KPI", DefaultVersion=6)
    first.CalculatedFields().Add("late_rate", "=late_w/orders_w", True)
    first.CalculatedFields().Add("avg_score", "=score_w/reviewed_w", True)
    first.CalculatedFields().Add("bad_rate", "=bad_w/reviewed_w", True)
    for field, caption, fmt in [("revenue", "Выручка, R$", "#,##0"), ("orders_w", "Заказы", "#,##0"),
                                ("avg_score", "Средняя оценка", "0.00"), ("late_rate", "Доля опозданий", "0.0%"),
                                ("bad_rate", "Доля оценок 1–2", "0.0%")]:
        set_fmt(first.AddDataField(first.PivotFields(field), caption, xlSum), fmt)
    pts["PT_KPI"] = first
    piv.Range("A1").Value = "Сводные таблицы — источник дашборда (лист «Данные»). Фильтруются срезами на дашборде."
    piv.Range("A1").Font.Bold = True

    make_pt("PT_Revenue", "H3", "month", [("revenue", "Выручка, R$ ", "#,##0")])
    make_pt("PT_LateMonth", "K3", "month", [("late_rate", "Доля опозданий ", "0.0%")])
    make_pt("PT_ScoreMonth", "N3", "month", [("avg_score", "Средняя оценка ", "0.00")])
    make_pt("PT_Delivery", "Q3", "delivery", [("avg_score", "Средняя оценка  ", "0.00")])
    pt = make_pt("PT_State", "T3", "state", [("late_rate", "Доля опозданий  ", "0.0%")])
    pt.PivotFields("state").AutoSort(xlDesc, "Доля опозданий  ")
    pt = make_pt("PT_Category", "W3", "category", [("revenue", "Выручка, R$  ", "#,##0")])
    pf = pt.PivotFields("category")
    pf.AutoSort(xlDesc, "Выручка, R$  ")
    pf.PivotFilters.Add2(Type=1, DataField=pt.DataFields("Выручка, R$  "), Value1=10)  # xlTopCount
    piv.Columns("A:Z").AutoFit()

    # --- Дашборд
    xl.ScreenUpdating = False
    dash.Activate()
    book.Windows(1).DisplayGridlines = False
    book.Windows(1).DisplayHeadings = False
    dash.Cells.Interior.Color = rgb("FFFFFF")
    dash.Columns("A").ColumnWidth = 2
    dash.Range("B1").Value = "Olist: выручка, доставка и отзывы покупателей"
    dash.Range("B1").Font.Size = 20
    dash.Range("B1").Font.Bold = True
    dash.Range("B2").Value = ("Опоздание — главный драйвер плохих отзывов: оценка падает с 4,3 до 2,3. "
                              "Срезы слева фильтруют все показатели и графики.")
    dash.Range("B2").Font.Color = rgb(MUTED)
    dash.Rows(1).RowHeight = 34

    left0, top_kpi = 200, 60
    kpis = [("Выручка, R$", "Выручка, R$", "#,##0"), ("Заказы", "Заказы", "#,##0"),
            ("Средняя оценка", "Средняя оценка", "0.00"), ("Доля опозданий", "Доля опозданий", "0.0%"),
            ("Доля оценок 1–2", "Доля оценок 1–2", "0.0%")]
    # KPI-плитки: подпись + значение из сводной через GETPIVOTDATA (ячейки под плитками скрыты)
    kpi_w, gap = 145, 12
    for i, (label, field, fmt) in enumerate(kpis):
        cell = dash.Cells(40, 30 + i)  # служебные ячейки за пределами экрана
        try:
            cell.Formula = f'=GETPIVOTDATA("{field}",\'Сводные\'!$A$3)'
        except Exception:
            cell.FormulaLocal = f'=ПОЛУЧИТЬ.ДАННЫЕ.СВОДНОЙ.ТАБЛИЦЫ("{field}";\'Сводные\'!$A$3)'
        set_fmt(cell, fmt)
        x = left0 + i * (kpi_w + gap)
        box = dash.Shapes.AddShape(5, x, top_kpi, kpi_w, 62)  # скруглённый прямоугольник
        box.Fill.ForeColor.RGB = rgb(SURFACE)
        box.Line.Visible = False
        box.Adjustments.SetItem(1, 0.12)
        tf = box.TextFrame2
        tf.VerticalAnchor = 1
        tf.MarginLeft = 10
        tf.TextRange.Text = label
        tf.TextRange.Font.Size = 10
        tf.TextRange.Font.Fill.ForeColor.RGB = rgb(MUTED)
        tf.TextRange.ParagraphFormat.Alignment = 1
        val = dash.Shapes.AddTextbox(1, x + 4, top_kpi + 22, kpi_w - 8, 36)
        val.Line.Visible = False
        val.Fill.Visible = False
        val.DrawingObject.Formula = "=" + cell.Address
        val.TextFrame2.TextRange.Font.Size = 20
        val.TextFrame2.TextRange.Font.Bold = True
        val.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = rgb(ORANGE if "опозд" in label or "1–2" in label else INK)

    # --- Диаграммы (сводные диаграммы, 3 x 2)
    cw, ch, top_ch = 380, 215, 140
    specs = [
        ("PT_Revenue", 51, "Выручка по месяцам, R$", BLUE),
        ("PT_LateMonth", 4, "Доля заказов с опозданием по месяцам", ORANGE),
        ("PT_Delivery", 51, "Средняя оценка: вовремя vs с опозданием", None),
        ("PT_ScoreMonth", 4, "Средняя оценка по месяцам", BLUE),
        ("PT_State", 57, "Доля опозданий по штатам", ORANGE),
        ("PT_Category", 57, "Топ-10 категорий по выручке, R$", BLUE),
    ]
    for k, (pt_name, ctype, title, color) in enumerate(specs):
        x = left0 + (k % 2) * (cw + 14)
        y = top_ch + (k // 2) * (ch + 14)
        shp = dash.Shapes.AddChart2(-1, ctype, x, y, cw, ch)
        chart = shp.Chart
        chart.SetSourceData(pts[pt_name].TableRange1)
        chart.HasTitle = True
        chart.ChartTitle.Text = title
        chart.ChartTitle.Format.TextFrame2.TextRange.Font.Size = 11
        chart.ChartTitle.Format.TextFrame2.TextRange.Font.Bold = True
        chart.HasLegend = False
        chart.ShowAllFieldButtons = False
        chart.ChartArea.Format.Line.Visible = False
        s = chart.SeriesCollection(1)
        if ctype == 4:
            s.Format.Line.ForeColor.RGB = rgb(color)
            s.Format.Line.Weight = 2
        elif color:
            s.Format.Fill.ForeColor.RGB = rgb(color)
        else:  # вовремя / с опозданием — разные цвета точек
            s.Format.Fill.ForeColor.RGB = rgb(BLUE)
            if s.Points().Count >= 2:
                s.Points(2).Format.Fill.ForeColor.RGB = rgb(ORANGE)
            s.HasDataLabels = True
            s.DataLabels().NumberFormatLinked = True
        if ctype in (51, 57):
            chart.ChartGroups(1).GapWidth = 60
        if ctype == 57:
            chart.Axes(1).ReversePlotOrder = True
        if ctype == 4 and "оценка" in title:
            chart.Axes(2).MinimumScale = 3.5
            chart.Axes(2).MaximumScale = 4.5
        chart.Axes(2).MajorGridlines.Format.Line.ForeColor.RGB = rgb("E6E5E0")
        shp.Name = "ch_" + pt_name

    # --- Срезы
    slicer_specs = [("month", "Месяц", 175, 3), ("state", "Штат", 200, 3), ("category", "Категория", 240, 1)]
    y = 60
    for field, caption, h, cols in slicer_specs:
        sc = book.SlicerCaches.Add2(pts["PT_KPI"], field)
        sl = sc.Slicers.Add(SlicerDestination=dash, Name=f"sl_{field}", Caption=caption, Top=y, Left=10, Width=178, Height=h)
        sl.Top, sl.Left, sl.Width, sl.Height = y, 10, 178, h
        sl.Caption = caption
        sl.NumberOfColumns = cols
        sl.Style = "SlicerStyleLight1"
        for name, pt_obj in pts.items():
            if name != "PT_KPI":
                sc.PivotTables.AddPivotTable(pt_obj)
        y += h + 8

    # --- Выводы под графиками
    y_txt = top_ch + 3 * (ch + 14) + 6
    notes = dash.Shapes.AddTextbox(1, left0, y_txt, 2 * cw + 14, 90)
    notes.Line.Visible = False
    notes.TextFrame2.TextRange.Text = (
        "Главные выводы\n"
        "• Опоздавшие заказы получают в среднем 2,3 балла против 4,3; доля оценок 1–2 — 62% против 9%.\n"
        "• Пики опозданий — ноябрь 2017 (Black Friday, 12%) и февраль–март 2018 (14–19%); в эти же месяцы проседает оценка.\n"
        "• Северо-восток (AL, MA, SE, PI, CE) опаздывает в 14–21% заказов при среднем 6,8% — обещанные сроки занижены.\n"
        "• Действие: пересчитать обещанную дату для дальних штатов и пиковых месяцев; продавцам с плохими показателями — уведомление (лист «Продавцы»)."
    )
    notes.TextFrame2.TextRange.Font.Size = 10
    notes.TextFrame.Characters(1, len("Главные выводы")).Font.Bold = True

    # --- Кнопка на листе «Продавцы»
    ws = S("Продавцы")
    btn = ws.Shapes.AddShape(5, ws.Range("D2").Left, ws.Range("D2").Top + 4, 200, 32)
    btn.Name = "btnLetter"
    btn.Fill.ForeColor.RGB = rgb(BLUE)
    btn.Line.Visible = False
    btn.TextFrame2.TextRange.Text = "Сформировать письмо"
    btn.TextFrame2.TextRange.Font.Bold = True
    btn.TextFrame2.TextRange.Font.Size = 12
    btn.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = rgb("FFFFFF")
    btn.TextFrame2.TextRange.ParagraphFormat.Alignment = 2
    btn.TextFrame2.VerticalAnchor = 3
    btn.OnAction = "GenerateQualityLetter"

    S("Данные").Range("A1:J1").Font.Bold = True
    S("Данные").Columns("A:J").AutoFit()

    vba_ok = False
    try:
        book.VBProject.VBComponents.Import(str(BAS))
        vba_ok = True
    except Exception:
        print("! Нет доступа к проекту VBA: импортируйте vba/QualityLetter.bas вручную (Alt+F11 -> File -> Import).")

    dash.Activate()
    dash.Range("A1").Select()
    xl.ScreenUpdating = True
    if XLSM.exists():
        XLSM.unlink()
    book.SaveAs(str(XLSM), FileFormat=52)
    book.Close(False)
    print(f"Сохранено: {XLSM.name}; VBA-модуль {'встроен' if vba_ok else 'НЕ встроен'}")
finally:
    for b in list(xl.Workbooks):
        b.Close(False)
    xl.Quit()
    del xl
    XLSX_TMP.unlink(missing_ok=True)
