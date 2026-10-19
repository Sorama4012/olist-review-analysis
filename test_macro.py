import os, win32com.client as w
xl = w.DispatchEx("Excel.Application"); xl.DisplayAlerts = False
try:
    b = xl.Workbooks.Open(os.path.abspath("report.xlsm"))
    s, l = b.Worksheets("Продавцы"), b.Worksheets("Письмо")
    print("modules:", [c.Name for c in b.VBProject.VBComponents if c.Type == 1])
    print("button:", s.Shapes("btnLetter").OnAction)
    tbl = s.ListObjects("tblSellers")
    for pos in (1, tbl.ListRows.Count):  # худший и лучший продавец
        s.Range("SelectedSeller").Value = tbl.DataBodyRange.Cells(pos, 1).Value
        xl.Run("BuildLetter", True)
        print("-" * 60, "seller", pos)
        for r in range(2, 35):
            t = l.Cells(r, 2).Text
            if t: print(t)
    b.Close(False)
finally:
    xl.Quit()
