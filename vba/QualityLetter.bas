Attribute VB_Name = "QualityLetter"
Option Explicit

' Формирует письмо-уведомление продавцу о проблемах с качеством.
' Источник данных: таблица tblSellers на листе «Продавцы» (выгрузка запроса 9 из queries.sql).
' Продавец выбирается в ячейке SelectedSeller (выпадающий список).
' Нормы платформы и срок исправления берутся из именованных ячеек
' PlatformBadShare, PlatformLateShare, FixDays, SenderName.

Public Sub GenerateQualityLetter()
    BuildLetter False
End Sub

' silent = True — без диалогов (для автотеста из build_report.py)
Public Sub BuildLetter(Optional ByVal silent As Boolean = False)
    Dim wsS As Worksheet, wsL As Worksheet
    Set wsS = ThisWorkbook.Worksheets("Продавцы")
    Set wsL = ThisWorkbook.Worksheets("Письмо")

    Dim sellerId As String
    sellerId = Trim$(CStr(wsS.Range("SelectedSeller").Value))
    If sellerId = "" Then
        If Not silent Then MsgBox "Выберите продавца в жёлтой ячейке на листе «Продавцы».", vbExclamation, "Письмо продавцу"
        Exit Sub
    End If

    Dim tbl As ListObject
    Set tbl = wsS.ListObjects("tblSellers")

    Dim pos As Variant
    pos = Application.Match(sellerId, tbl.ListColumns("seller_id").DataBodyRange, 0)
    If IsError(pos) Then
        If Not silent Then MsgBox "Продавец " & sellerId & " не найден в таблице.", vbExclamation, "Письмо продавцу"
        Exit Sub
    End If

    Dim city As String, state As String, orders As Long
    Dim avgScore As Double, badShare As Double, lateShare As Double, delayDays As Variant
    city = Col(tbl, pos, "seller_city")
    state = Col(tbl, pos, "seller_state")
    orders = Col(tbl, pos, "reviewed_orders")
    avgScore = Col(tbl, pos, "avg_score")
    badShare = Col(tbl, pos, "bad_share")
    lateShare = Col(tbl, pos, "late_share")
    delayDays = Col(tbl, pos, "avg_delay_days")

    Dim normBad As Double, normLate As Double, fixDays As Long, deadline As Date
    normBad = ThisWorkbook.Names("PlatformBadShare").RefersToRange.Value
    normLate = ThisWorkbook.Names("PlatformLateShare").RefersToRange.Value
    fixDays = ThisWorkbook.Names("FixDays").RefersToRange.Value
    deadline = Date + fixDays

    Dim badProblem As Boolean, lateProblem As Boolean
    badProblem = badShare > normBad
    lateProblem = lateShare > normLate
    wsL.Range("B2:B60").ClearContents
    If Not badProblem And Not lateProblem Then
        If silent Then ThisWorkbook.Worksheets("Письмо").Range("B2").Value = "OK: no letter needed": Exit Sub
        MsgBox "Показатели продавца в пределах норм платформы — уведомление не требуется." & vbCrLf & _
               "Доля оценок 1–2: " & Pct(badShare) & " (норма " & Pct(normBad) & ")" & vbCrLf & _
               "Опоздания: " & Pct(lateShare) & " (норма " & Pct(normLate) & ")", vbInformation, "Письмо продавцу"
        Exit Sub
    End If

    Dim level As String
    If badShare >= 2 * normBad Or lateShare >= 2 * normLate Then
        level = "критический"
    Else
        level = "повышенный"
    End If

    Dim subj As String
    subj = "Уведомление о качестве обслуживания: продавец " & Left$(sellerId, 8) & " — уровень риска " & level

    Dim lines As Collection
    Set lines = New Collection
    lines.Add "Уважаемый партнёр!"
    lines.Add ""
    lines.Add "По итогам анализа заказов вашего магазина (ID " & sellerId & ", " & PropCase(city) & ", " & state & ")"
    lines.Add "мы зафиксировали отклонения показателей качества от норм платформы. Уровень риска: " & level & "."
    lines.Add ""
    lines.Add "Показатели по " & orders & " оценённым заказам:"
    lines.Add "  • средняя оценка покупателей: " & Format$(avgScore, "0.00") & " из 5;"
    lines.Add "  • доля отзывов с оценкой 1–2: " & Pct(badShare) & " при норме платформы " & Pct(normBad) & Flag(badProblem) & ";"
    lines.Add "  • доля заказов, доставленных позже обещанной даты: " & Pct(lateShare) & " при норме " & Pct(normLate) & Flag(lateProblem) & ";"
    If Len(CStr(delayDays)) > 0 Then
        lines.Add "  • среднее опоздание: " & Format$(delayDays, "0.0") & " дн."
    End If
    lines.Add ""
    lines.Add "По нашим данным, опоздание — главная причина низких оценок: заказы, доставленные с опозданием,"
    lines.Add "получают в среднем 2,3 балла против 4,3 у доставленных вовремя."
    lines.Add ""
    lines.Add "Просим в срок до " & Format$(deadline, "dd.mm.yyyy") & " (" & fixDays & " календарных дней):"
    If lateProblem Then
        lines.Add "  1. Проверить сроки передачи заказов в доставку и реалистичность обещанных дат."
    End If
    If badProblem Then
        lines.Add "  " & IIf(lateProblem, "2", "1") & ". Разобрать отзывы с оценкой 1–2 и устранить причины (качество товара, комплектация, описание)."
    End If
    lines.Add "  " & IIf(lateProblem And badProblem, "3", IIf(lateProblem Or badProblem, "2", "1")) & ". Направить нам план корректирующих действий."
    lines.Add ""
    lines.Add "Если к указанной дате показатели не приблизятся к нормам платформы, мы будем вынуждены"
    lines.Add "ограничить продвижение ваших товаров в поиске до стабилизации качества."
    lines.Add ""
    lines.Add "С уважением,"
    lines.Add CStr(ThisWorkbook.Names("SenderName").RefersToRange.Value)
    lines.Add "Отдел качества продавцов, Olist"

    ' Выводим письмо на лист «Письмо»
    wsL.Range("B2").Value = "Тема: " & subj
    wsL.Range("B2").Font.Bold = True
    Dim i As Long
    For i = 1 To lines.Count
        wsL.Cells(i + 3, 2).Value = "'" & lines(i)
    Next i
    wsL.Activate
    wsL.Range("A1").Select

    Dim body As String
    For i = 1 To lines.Count
        body = body & lines(i) & vbCrLf
    Next i

    If silent Then Exit Sub
    If MsgBox("Письмо сформировано на листе «Письмо»." & vbCrLf & vbCrLf & _
              "Открыть его как черновик в Outlook?", vbYesNo + vbQuestion, "Письмо продавцу") = vbYes Then
        CreateOutlookDraft subj, body
    End If
End Sub

Private Sub CreateOutlookDraft(ByVal subj As String, ByVal body As String)
    Dim ol As Object, mail As Object
    On Error Resume Next
    Set ol = CreateObject("Outlook.Application")
    On Error GoTo 0
    If ol Is Nothing Then
        MsgBox "Outlook не найден. Текст письма можно скопировать с листа «Письмо».", vbInformation, "Письмо продавцу"
        Exit Sub
    End If
    Set mail = ol.CreateItem(0)
    mail.Subject = subj
    mail.Body = body
    mail.Display   ' только черновик: письмо не отправляется автоматически
End Sub

Private Function Col(tbl As ListObject, ByVal pos As Long, ByVal name As String) As Variant
    Col = tbl.DataBodyRange.Cells(pos, tbl.ListColumns(name).Index).Value
End Function

Private Function Pct(ByVal x As Double) As String
    Pct = Format$(x * 100, "0.0") & "%"
End Function

Private Function Flag(ByVal isProblem As Boolean) As String
    If isProblem Then Flag = " — выше нормы" Else Flag = ""
End Function

Private Function PropCase(ByVal s As String) As String
    PropCase = StrConv(s, vbProperCase)
End Function
