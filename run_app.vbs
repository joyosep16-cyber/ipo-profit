Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "cmd /c ""C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe"" -m streamlit run app.py --browser.gatherUsageStats false --server.headless true", 0, False

' Poll every 1s until Streamlit is ready (max 30s)
Dim i
For i = 1 To 30
    WScript.Sleep 1000
    On Error Resume Next
    Dim http
    Set http = CreateObject("MSXML2.XMLHTTP")
    http.Open "GET", "http://localhost:8501/_stcore/health", False
    http.Send
    If Err.Number = 0 And http.Status = 200 Then
        Set http = Nothing
        Exit For
    End If
    On Error GoTo 0
    Set http = Nothing
Next

WshShell.Run "http://localhost:8501"
Set WshShell = Nothing
Set fso = Nothing
