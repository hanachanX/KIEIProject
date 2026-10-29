' kiei.vbs - start KIEI (shogi analysis tool) without a black console window.
' If it does not start, look at kiei_error.txt in the same folder.
' Double-clicking a .kif file passes that file as the first argument.

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' the folder where this vbs lives (so you can move the folder)
appdir  = fso.GetParentFolderName(WScript.ScriptFullName)
script  = appdir & "\app.py"
logfile = appdir & "\kiei_error.txt"

If Not fso.FileExists(script) Then
  MsgBox "Not found:" & vbCrLf & script, 16, "KIEI"
  WScript.Quit 1
End If

' same as "cd" in a bat file
sh.CurrentDirectory = appdir

' run "pythonw" found via PATH; errors are saved into a text file
q = Chr(34)
arg = ""
If WScript.Arguments.Count > 0 Then arg = " " & q & WScript.Arguments(0) & q
cmd = "cmd /c " & q & "pythonw " & q & script & q & arg & " >" & q & logfile & q & " 2>&1" & q

' 0 = hide window, False = do not wait for the program to finish
sh.Run cmd, 0, False
