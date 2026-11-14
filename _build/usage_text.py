"""배포판 언어별 사용법 글 (USAGE_TEXT_VER 1.0.1) — make_release.py 1.8.0 이 씀
- 한국어(사용법.txt)·일본어(お読みください.txt)는 make_release.py 의 USAGE·USAGE_JA
- 여기는 나머지 8개: 파일 이름은 그 언어로(사람들이 이름만 보고 자기 언어를 찾게)
- 메뉴 이름은 bin\\lang\\<언어>.json 의 번역과 같게 씀(화면과 다르면 못 찾음)
- {ver} 자리에 버전, 맨 아래 {others} 자리에 다른 언어 파일 목록이 들어감
"""
USAGE_TEXT_VER = "1.0.1"

# (언어 코드, 파일 이름, Guide 폴더 안 그림 폴더 이름) — 순서 = 목록에 보이는 순서
FILES = [
    ("en", "README.txt", "English"),
    ("ko", "사용법.txt", "한국어"),
    ("ja", "お読みください.txt", "日本語"),
    ("zh_CN", "使用说明.txt", "简体中文"),
    ("zh_TW", "使用說明.txt", "繁體中文"),
    ("de", "Anleitung.txt", "Deutsch"),
    ("es", "Léame.txt", "Español"),
    ("fr", "Lisez-moi.txt", "Français"),
    ("pt_BR", "Leia-me.txt", "Português"),
    ("ru", "Инструкция.txt", "Русский"),
]

TEXT = {}

TEXT["en"] = r"""4Dir v{ver} — free multi-pane (up to 20 panes) tabbed file manager for Windows 10/11

[Install]
  0. (If you downloaded it) Before extracting: right-click the zip > Properties > check 'Unblock' at the bottom > OK.
     Otherwise Windows shows a security warning every time you start 4Dir.
     (Already extracted? Right-click 4Dir.exe and 4Dir.vbs > Properties > check 'Unblock'.)
  1. Copy this folder anywhere you like (e.g. D:\Tools\4Dir). There is no installer.
     (Don't run it straight from a network drive - copy it to your PC.)
  2. Double-click 4Dir.exe. No Python installation needed (it's in the runtime folder).
     (If 4Dir.exe is blocked by Windows security (SmartScreen) or antivirus, use 4Dir.vbs - it does the same thing.
      If the SmartScreen window appears: 'More info' > 'Run anyway'.)
  3. Desktop shortcut: right-click 4Dir.exe > Send to > Desktop (create shortcut).
  Uninstall: delete this folder. Nothing is left in the registry or the system.

[Main features]
  - Layout icons at the top: 1 / 2 / 3 / 4 / 6 panes, grid button = custom (columns x rows, up to 5 x 4)
  - Tabs in every pane: Ctrl+T new tab, Ctrl+W close, Ctrl+Shift+T reopen closed tab, middle-click = new tab / close
  - Search everything: Ctrl+Shift+F (file-name search across drives; building the index the first time takes a few minutes)
    What gets searched: Tools > Search Scope (external drives, network and Google Drive must be turned on there)
  - Favorites: drag a folder onto the favorites bar / right-click a folder > ★ Add to 4Dir Favorites / Ctrl+D
    Favorites > Organize favorites: delete several at once, reorder, group them like folders, find folders that no longer exist
  - Dragging tabs: left/right in the tab bar = reorder, drop on another pane = move it there, drop outside 4Dir = new window
  - Batch rename: select several items and press F2 (or Tools > Batch rename) / Ctrl+Z = undo the last operation
  - Quick filter: Ctrl+F (filter the current folder by name)
  - Copy to the other pane F6, move Shift+F6 (to the pane you used just before)
  - Version control icons: SVN is shown by 4Dir itself; Git, Perforce etc. show the icons of the tools installed on your PC (TortoiseGit, P4EXP ...)
    If the icons don't appear: Tools > Overlay icon order (Windows) (Windows uses only the first 11)
  - Icon views (small / medium / large icons) show previews of image files (turn off: View > Show > Image previews (icon views))
  - View menu: details/icons, hidden items, file name extensions, path buttons, theme (system/light/dark), colors, always on top, CPU/GPU display
  - View > Language: 16 languages. Default = your Windows display language. Applied after restarting 4Dir.
    Translations are in bin\lang\<language>.json - you can edit them with Notepad.
  - Save/Load windows: save the current tab layout under a name / restore from the automatic record after a crash
  - Tools > Explorer Check: finds and fixes the cause when Windows File Explorer is slow
    (If 4Dir itself won't open, run bin\탐색기 점검.vbs directly - that is Explorer Check.)

[If something goes wrong]
  Tools > 'Save log for problem report' creates a zip in the 'reports' folder inside 4Dir and shows it to you. Please send that file.
  (If 4Dir doesn't open at all, send the whole bin\log folder.)
  Contact: support@4dir.net / Board: https://github.com/gkstmdahr/4Dir/discussions

[More]
  Website (guide with pictures): https://4dir.net
  Pictures of each screen: Guide\English folder
  4Dir is free and open source (GPL-3.0). Licenses of the bundled Python, PySide6 (Qt) and pywin32 are in the licenses folder.

{others}
"""

TEXT["zh_CN"] = r"""4Dir v{ver} — 免费的 Windows 10/11 多窗格（最多 20 格）标签式文件管理器

[安装]
  0. （从网上下载时）解压前：右键 zip 文件 > 属性 > 勾选下方的“解除锁定” > 确定。
     不这样做的话，每次启动 4Dir 时 Windows 都会弹出安全警告。
     （已经解压了？右键 4Dir.exe 和 4Dir.vbs > 属性 > 勾选“解除锁定”。）
  1. 把这个文件夹整个复制到任意位置（例如 D:\Tools\4Dir）。无需安装。
     （不要直接从网络驱动器运行，请复制到本机。）
  2. 双击 4Dir.exe 即可运行。无需安装 Python（已包含在 runtime 文件夹中）。
     （如果 4Dir.exe 被 Windows 安全中心（SmartScreen）或杀毒软件拦截，请用 4Dir.vbs 启动——作用相同。
      出现 SmartScreen 窗口时：“更多信息” > “仍要运行”。）
  3. 桌面快捷方式：右键 4Dir.exe > 发送到 > 桌面快捷方式。
  卸载：删除整个文件夹即可。不会在注册表或系统中留下任何东西。

[常用功能]
  - 顶部布局图标：1 / 2 / 3 / 4 / 6 格，网格按钮 = 自定义（列 x 行，最多 5 x 4）
  - 每个窗格都有标签：Ctrl+T 新标签，Ctrl+W 关闭，Ctrl+Shift+T 重新打开关闭的标签，中键单击 = 新标签/关闭
  - 全盘搜索：Ctrl+Shift+F（跨驱动器的文件名搜索；第一次建立索引需要几分钟）
    搜索范围：工具 > 搜索范围（外接硬盘、网络、Google 云端硬盘需要在这里打开才会被搜索）
  - 收藏夹：把文件夹拖到收藏栏 / 右键文件夹 > ★ 添加到 4Dir 收藏夹 / Ctrl+D
    收藏夹 > 整理收藏：一次删除多个、调整顺序、分组（像文件夹一样归类）、查找已不存在的文件夹
  - 拖动标签：在标签栏内左右拖 = 调整顺序，放到其他窗格 = 移到那里，放到 4Dir 窗口外 = 新窗口
  - 批量重命名：选中多个后按 F2（或 工具 > 批量重命名）/ Ctrl+Z = 撤销上一步操作
  - 快速筛选：Ctrl+F（按名称筛选当前文件夹）
  - 复制到另一窗格 F6，移动 Shift+F6（到刚才使用的窗格）
  - 版本控制图标：SVN 由 4Dir 直接显示；Git、Perforce 等显示本机已安装工具（TortoiseGit、P4EXP 等）的图标
    图标不显示时：工具 > 覆盖图标顺序（Windows）（Windows 只使用前 11 个）
  - 图标视图（小/中/大图标）会显示图片预览（关闭：查看 > 显示 > 图片预览（图标视图））
  - 查看菜单：详细信息/图标、隐藏的项目、文件扩展名、路径按钮、主题（系统/浅色/深色）、颜色、总在最前、CPU/GPU 显示
  - 查看 > 语言（Language）：16 种语言。默认跟随 Windows 显示语言。重新启动 4Dir 后生效。
    翻译文件在 bin\lang\<语言>.json，可以用记事本修改。
  - 保存/加载窗口：把当前标签布局命名保存 / 意外关闭后从自动记录恢复
  - 工具 > Explorer Check（资源管理器检查）：Windows 资源管理器变慢时查找并解决原因
    （4Dir 本身打不开时，直接运行 bin\탐색기 점검.vbs，即 Explorer Check。）

[遇到问题时]
  工具 >“保存问题报告日志”会在 4Dir 文件夹内的 reports 中生成 zip 文件并打开给你看。请把这个文件发给我们。
  （4Dir 完全打不开时，请发送整个 bin\log 文件夹。）
  联系方式：support@4dir.net / 留言板：https://github.com/gkstmdahr/4Dir/discussions

[更多]
  网站（带图的说明）：https://4dir.net
  各画面的图片：Guide\简体中文 文件夹
  4Dir 是免费的开源软件（GPL-3.0）。随附的 Python、PySide6（Qt）、pywin32 的许可证在 licenses 文件夹中。

{others}
"""

TEXT["zh_TW"] = r"""4Dir v{ver} — 免費的 Windows 10/11 多窗格（最多 20 格）分頁式檔案管理器

[安裝]
  0. （從網路下載時）解壓縮前：在 zip 檔上按右鍵 > 內容 > 勾選下方的「解除封鎖」 > 確定。
     不這樣做的話，每次啟動 4Dir 時 Windows 都會跳出安全性警告。
     （已經解壓縮了？在 4Dir.exe 和 4Dir.vbs 上按右鍵 > 內容 > 勾選「解除封鎖」。）
  1. 把這個資料夾整個複製到任意位置（例如 D:\Tools\4Dir）。不需要安裝。
     （不要直接從網路磁碟機執行，請複製到本機。）
  2. 按兩下 4Dir.exe 即可執行。不需要安裝 Python（已包含在 runtime 資料夾中）。
     （如果 4Dir.exe 被 Windows 安全性（SmartScreen）或防毒軟體攔截，請用 4Dir.vbs 啟動——作用相同。
      出現 SmartScreen 視窗時：「其他資訊」 > 「仍要執行」。）
  3. 桌面捷徑：在 4Dir.exe 上按右鍵 > 傳送到 > 桌面 (建立捷徑)。
  解除安裝：刪除整個資料夾即可。不會在登錄或系統中留下任何東西。

[常用功能]
  - 上方版面配置圖示：1 / 2 / 3 / 4 / 6 格，格線按鈕 = 自訂（欄 x 列，最多 5 x 4）
  - 每個窗格都有分頁：Ctrl+T 新分頁，Ctrl+W 關閉，Ctrl+Shift+T 重新開啟關閉的分頁，按滑鼠中鍵 = 新分頁/關閉
  - 全部搜尋：Ctrl+Shift+F（跨磁碟機的檔名搜尋；第一次建立索引需要幾分鐘）
    搜尋範圍：工具 > 搜尋範圍（外接硬碟、網路、Google 雲端硬碟需要在這裡開啟才會被搜尋）
  - 我的最愛：把資料夾拖到我的最愛列 / 在資料夾上按右鍵 > ★ 加入 4Dir 我的最愛 / Ctrl+D
    我的最愛 > 整理我的最愛：一次刪除多個、調整順序、分組（像資料夾一樣歸類）、找出已不存在的資料夾
  - 拖曳分頁：在分頁列內左右拖 = 調整順序，放到其他窗格 = 移到那裡，放到 4Dir 視窗外 = 新視窗
  - 批次重新命名：選取多個後按 F2（或 工具 > 批次重新命名）/ Ctrl+Z = 復原上一個動作
  - 快速篩選：Ctrl+F（依名稱篩選目前的資料夾）
  - 複製到另一窗格 F6，移動 Shift+F6（到剛才使用的窗格）
  - 版本控制圖示：SVN 由 4Dir 直接顯示；Git、Perforce 等顯示本機已安裝工具（TortoiseGit、P4EXP 等）的圖示
    圖示沒有出現時：工具 > 覆疊圖示順序（Windows）（Windows 只使用前 11 個）
  - 圖示檢視（小/中/大圖示）會顯示圖片預覽（關閉：檢視 > 顯示 > 圖片預覽（圖示檢視））
  - 檢視選單：詳細資料/圖示、隱藏的項目、副檔名、路徑按鈕、佈景主題（系統/淺色/深色）、色彩、永遠在最上層、CPU/GPU 顯示
  - 檢視 > 語言（Language）：16 種語言。預設跟隨 Windows 顯示語言。重新啟動 4Dir 後生效。
    翻譯檔在 bin\lang\<語言>.json，可以用記事本修改。
  - 儲存/載入視窗：把目前的分頁配置命名儲存 / 意外關閉後從自動記錄復原
  - 工具 > Explorer Check（檔案總管檢查）：Windows 檔案總管變慢時找出並解決原因
    （4Dir 本身打不開時，直接執行 bin\탐색기 점검.vbs，即 Explorer Check。）

[遇到問題時]
  工具 >「儲存問題回報記錄」會在 4Dir 資料夾內的 reports 中建立 zip 檔並開啟給你看。請把這個檔案寄給我們。
  （4Dir 完全打不開時，請寄送整個 bin\log 資料夾。）
  聯絡方式：support@4dir.net / 留言板：https://github.com/gkstmdahr/4Dir/discussions

[更多]
  網站（附圖說明）：https://4dir.net
  各畫面的圖片：Guide\繁體中文 資料夾
  4Dir 是免費的開放原始碼軟體（GPL-3.0）。隨附的 Python、PySide6（Qt）、pywin32 的授權在 licenses 資料夾中。

{others}
"""

TEXT["de"] = r"""4Dir v{ver} — kostenloser Dateimanager für Windows 10/11 mit mehreren Bereichen (bis zu 20) und Tabs

[Installation]
  0. (Wenn heruntergeladen) Vor dem Entpacken: Rechtsklick auf die ZIP-Datei > Eigenschaften > unten 'Zulassen' anhaken > OK.
     Sonst zeigt Windows bei jedem Start von 4Dir eine Sicherheitswarnung.
     (Schon entpackt? Rechtsklick auf 4Dir.exe und 4Dir.vbs > Eigenschaften > 'Zulassen' anhaken.)
  1. Diesen Ordner an einen beliebigen Ort kopieren (z. B. D:\Tools\4Dir). Keine Installation nötig.
     (Nicht direkt von einem Netzlaufwerk starten - auf den eigenen PC kopieren.)
  2. 4Dir.exe doppelklicken. Python muss nicht installiert sein (liegt im Ordner runtime).
     (Wenn 4Dir.exe von der Windows-Sicherheit (SmartScreen) oder dem Virenscanner blockiert wird, 4Dir.vbs verwenden - macht dasselbe.
      Erscheint das SmartScreen-Fenster: 'Weitere Informationen' > 'Trotzdem ausführen'.)
  3. Desktop-Verknüpfung: Rechtsklick auf 4Dir.exe > Senden an > Desktop (Verknüpfung erstellen).
  Deinstallieren: diesen Ordner löschen. In Registry und System bleibt nichts zurück.

[Wichtige Funktionen]
  - Layout-Symbole oben: 1 / 2 / 3 / 4 / 6 Bereiche, Raster-Schaltfläche = eigenes Raster (Spalten x Zeilen, bis 5 x 4)
  - Tabs in jedem Bereich: Strg+T neuer Tab, Strg+W schließen, Strg+Umschalt+T geschlossenen Tab wieder öffnen, Mittelklick = neuer Tab / schließen
  - Alles durchsuchen: Strg+Umschalt+F (Dateinamensuche über alle Laufwerke; der Index wird beim ersten Mal in einigen Minuten erstellt)
    Was durchsucht wird: Extras > Suchbereich (externe Laufwerke, Netzwerk und Google Drive müssen dort eingeschaltet werden)
  - Favoriten: Ordner auf die Favoritenleiste ziehen / Rechtsklick auf Ordner > ★ Zu 4Dir-Favoriten hinzufügen / Strg+D
    Favoriten > Favoriten organisieren: mehrere löschen, Reihenfolge ändern, gruppieren (wie Ordner), nicht mehr vorhandene Ordner finden
  - Tabs ziehen: in der Tableiste nach links/rechts = Reihenfolge, auf anderen Bereich = dorthin verschieben, außerhalb von 4Dir = neues Fenster
  - Stapelumbenennung: mehrere auswählen und F2 drücken (oder Extras > Stapelumbenennung) / Strg+Z = letzten Vorgang rückgängig
  - Schnellfilter: Strg+F (aktuellen Ordner nach Namen filtern)
  - In den anderen Bereich kopieren F6, verschieben Umschalt+F6 (in den zuletzt benutzten Bereich)
  - Versionskontroll-Symbole: SVN zeigt 4Dir selbst an; Git, Perforce usw. zeigen die Symbole der auf dem PC installierten Tools (TortoiseGit, P4EXP ...)
    Erscheinen keine Symbole: Extras > Overlay-Symbol-Reihenfolge (Windows) (Windows nutzt nur die ersten 11)
  - Symbolansichten (kleine / mittelgroße / große Symbole) zeigen eine Vorschau von Bildern (abschalten: Ansicht > Einblenden > Bildvorschau (Symbolansichten))
  - Menü Ansicht: Details/Symbole, ausgeblendete Elemente, Dateinamenerweiterungen, Pfad-Schaltflächen, Design (System/hell/dunkel), Farben, immer im Vordergrund, CPU/GPU-Anzeige
  - Ansicht > Sprache (Language): 16 Sprachen. Standard = Windows-Anzeigesprache. Wirkt nach Neustart von 4Dir.
    Die Übersetzungen liegen in bin\lang\<Sprache>.json - mit dem Editor änderbar.
  - Fenster speichern/laden: aktuelle Tab-Anordnung unter einem Namen speichern / nach einem Absturz aus der Autoaufzeichnung wiederherstellen
  - Extras > Explorer Check (Explorer-Diagnose): findet und behebt die Ursache, wenn der Windows-Explorer langsam ist
    (Startet 4Dir selbst nicht, bin\탐색기 점검.vbs direkt ausführen - das ist Explorer Check.)

[Bei Problemen]
  Extras > 'Protokoll für Fehlerbericht speichern' erstellt eine ZIP-Datei im Ordner 'reports' von 4Dir und zeigt sie an. Bitte diese Datei schicken.
  (Startet 4Dir gar nicht, bitte den ganzen Ordner bin\log schicken.)
  Kontakt: support@4dir.net / Forum: https://github.com/gkstmdahr/4Dir/discussions

[Mehr]
  Website (Anleitung mit Bildern): https://4dir.net
  Bilder der einzelnen Fenster: Ordner Guide\Deutsch
  4Dir ist kostenlos und quelloffen (GPL-3.0). Die Lizenzen von Python, PySide6 (Qt) und pywin32 liegen im Ordner licenses.

{others}
"""

TEXT["es"] = r"""4Dir v{ver} — gestor de archivos gratuito para Windows 10/11 con varios paneles (hasta 20) y pestañas

[Instalación]
  0. (Si lo descargó) Antes de descomprimir: clic derecho en el zip > Propiedades > marque 'Desbloquear' abajo > Aceptar.
     Si no, Windows mostrará una advertencia de seguridad cada vez que abra 4Dir.
     (¿Ya lo descomprimió? Clic derecho en 4Dir.exe y 4Dir.vbs > Propiedades > marque 'Desbloquear'.)
  1. Copie esta carpeta donde quiera (p. ej. D:\Tools\4Dir). No hay instalador.
     (No lo ejecute directamente desde una unidad de red: cópielo a su PC.)
  2. Haga doble clic en 4Dir.exe. No hace falta instalar Python (está en la carpeta runtime).
     (Si la seguridad de Windows (SmartScreen) o el antivirus bloquea 4Dir.exe, use 4Dir.vbs: hace lo mismo.
      Si aparece la ventana de SmartScreen: 'Más información' > 'Ejecutar de todas formas'.)
  3. Acceso directo en el escritorio: clic derecho en 4Dir.exe > Enviar a > Escritorio (crear acceso directo).
  Desinstalar: borre esta carpeta. No queda nada en el registro ni en el sistema.

[Funciones principales]
  - Iconos de diseño arriba: 1 / 2 / 3 / 4 / 6 paneles, botón de cuadrícula = personalizado (columnas x filas, hasta 5 x 4)
  - Pestañas en cada panel: Ctrl+T nueva pestaña, Ctrl+W cerrar, Ctrl+Mayús+T reabrir pestaña cerrada, clic central = nueva pestaña / cerrar
  - Buscar en todo: Ctrl+Mayús+F (búsqueda por nombre en todas las unidades; la primera vez el índice tarda unos minutos)
    Qué se busca: Herramientas > Ámbito de búsqueda (discos externos, red y Google Drive deben activarse ahí)
  - Favoritos: arrastre una carpeta a la barra de favoritos / clic derecho en una carpeta > ★ Añadir a favoritos de 4Dir / Ctrl+D
    Favoritos > Organizar favoritos: borrar varios a la vez, reordenar, agrupar (como carpetas), encontrar carpetas que ya no existen
  - Arrastrar pestañas: izquierda/derecha en la barra = reordenar, soltar en otro panel = moverla allí, soltar fuera de 4Dir = ventana nueva
  - Cambiar nombre en lote: seleccione varios y pulse F2 (o Herramientas > Cambiar nombre en lote) / Ctrl+Z = deshacer la última operación
  - Filtro rápido: Ctrl+F (filtrar la carpeta actual por nombre)
  - Copiar al otro panel F6, mover Mayús+F6 (al panel usado justo antes)
  - Iconos de control de versiones: SVN lo muestra 4Dir; Git, Perforce, etc. muestran los iconos de las herramientas instaladas en su PC (TortoiseGit, P4EXP...)
    Si no aparecen: Herramientas > Orden de iconos superpuestos (Windows) (Windows solo usa los 11 primeros)
  - Las vistas de iconos (pequeños / medianos / grandes) muestran una vista previa de las imágenes (desactivar: Vista > Mostrar > Vista previa de imágenes (vistas de iconos))
  - Menú Vista: detalles/iconos, elementos ocultos, extensiones de nombre de archivo, botones de ruta, tema (sistema/claro/oscuro), colores, siempre visible, CPU/GPU
  - Vista > Idioma (Language): 16 idiomas. Por defecto = idioma de Windows. Se aplica al reiniciar 4Dir.
    Las traducciones están en bin\lang\<idioma>.json y se pueden editar con el Bloc de notas.
  - Guardar/cargar ventanas: guardar la distribución de pestañas con un nombre / recuperar del registro automático tras un cierre inesperado
  - Herramientas > Explorer Check (diagnóstico del Explorador): busca y soluciona la causa cuando el Explorador de Windows va lento
    (Si 4Dir no abre, ejecute directamente bin\탐색기 점검.vbs, que es Explorer Check.)

[Si hay problemas]
  Herramientas > 'Guardar registro para informe de problemas' crea un zip en la carpeta 'reports' de 4Dir y se lo muestra. Envíenos ese archivo.
  (Si 4Dir no abre en absoluto, envíe toda la carpeta bin\log.)
  Contacto: support@4dir.net / Foro: https://github.com/gkstmdahr/4Dir/discussions

[Más]
  Sitio web (guía con imágenes): https://4dir.net
  Imágenes de cada pantalla: carpeta Guide\Español
  4Dir es gratuito y de código abierto (GPL-3.0). Las licencias de Python, PySide6 (Qt) y pywin32 incluidos están en la carpeta licenses.

{others}
"""

TEXT["fr"] = r"""4Dir v{ver} — gestionnaire de fichiers gratuit pour Windows 10/11, plusieurs volets (jusqu'à 20) et onglets

[Installation]
  0. (Si vous l'avez téléchargé) Avant d'extraire : clic droit sur le zip > Propriétés > cochez 'Débloquer' en bas > OK.
     Sinon, Windows affiche un avertissement de sécurité à chaque démarrage de 4Dir.
     (Déjà extrait ? Clic droit sur 4Dir.exe et 4Dir.vbs > Propriétés > cochez 'Débloquer'.)
  1. Copiez ce dossier où vous voulez (ex. D:\Tools\4Dir). Aucune installation.
     (Ne le lancez pas directement depuis un lecteur réseau : copiez-le sur votre PC.)
  2. Double-cliquez sur 4Dir.exe. Pas besoin d'installer Python (il est dans le dossier runtime).
     (Si 4Dir.exe est bloqué par la sécurité Windows (SmartScreen) ou l'antivirus, utilisez 4Dir.vbs : il fait la même chose.
      Si la fenêtre SmartScreen apparaît : 'Informations complémentaires' > 'Exécuter quand même'.)
  3. Raccourci sur le bureau : clic droit sur 4Dir.exe > Envoyer vers > Bureau (créer un raccourci).
  Désinstaller : supprimez ce dossier. Rien ne reste dans le registre ni dans le système.

[Fonctions principales]
  - Icônes de disposition en haut : 1 / 2 / 3 / 4 / 6 volets, bouton grille = personnalisé (colonnes x lignes, jusqu'à 5 x 4)
  - Onglets dans chaque volet : Ctrl+T nouvel onglet, Ctrl+W fermer, Ctrl+Maj+T rouvrir l'onglet fermé, clic du milieu = nouvel onglet / fermer
  - Tout rechercher : Ctrl+Maj+F (recherche par nom sur tous les lecteurs ; la première création de l'index prend quelques minutes)
    Ce qui est recherché : Outils > Étendue de la recherche (disques externes, réseau et Google Drive doivent y être activés)
  - Favoris : glissez un dossier sur la barre des favoris / clic droit sur un dossier > ★ Ajouter aux favoris 4Dir / Ctrl+D
    Favoris > Organiser les favoris : supprimer plusieurs à la fois, réordonner, grouper (comme des dossiers), trouver les dossiers disparus
  - Glisser les onglets : gauche/droite dans la barre = réordonner, sur un autre volet = l'y déplacer, hors de 4Dir = nouvelle fenêtre
  - Renommer par lot : sélectionnez plusieurs éléments et appuyez sur F2 (ou Outils > Renommer par lot) / Ctrl+Z = annuler la dernière opération
  - Filtre rapide : Ctrl+F (filtrer le dossier courant par nom)
  - Copier vers l'autre volet F6, déplacer Maj+F6 (vers le volet utilisé juste avant)
  - Icônes de gestion de versions : SVN est affiché par 4Dir lui-même ; Git, Perforce, etc. affichent les icônes des outils installés sur le PC (TortoiseGit, P4EXP...)
    Si elles n'apparaissent pas : Outils > Ordre des icônes de superposition (Windows) (Windows n'utilise que les 11 premières)
  - Les affichages icônes (petites / moyennes / grandes) montrent un aperçu des images (désactiver : Affichage > Afficher > Aperçu des images (affichage icônes))
  - Menu Affichage : détails/icônes, éléments masqués, extensions de noms de fichiers, boutons de chemin, thème (système/clair/sombre), couleurs, toujours au premier plan, CPU/GPU
  - Affichage > Langue (Language) : 16 langues. Par défaut = langue d'affichage de Windows. Appliqué après redémarrage de 4Dir.
    Les traductions sont dans bin\lang\<langue>.json et se modifient avec le Bloc-notes.
  - Enregistrer/charger les fenêtres : enregistrer la disposition des onglets sous un nom / restaurer depuis l'enregistrement automatique après un plantage
  - Outils > Explorer Check (diagnostic de l'Explorateur) : trouve et corrige la cause quand l'Explorateur Windows est lent
    (Si 4Dir lui-même ne s'ouvre pas, lancez directement bin\탐색기 점검.vbs : c'est Explorer Check.)

[En cas de problème]
  Outils > 'Enregistrer le journal pour signaler un problème' crée un zip dans le dossier 'reports' de 4Dir et vous le montre. Envoyez-nous ce fichier.
  (Si 4Dir ne s'ouvre pas du tout, envoyez tout le dossier bin\log.)
  Contact : support@4dir.net / Forum : https://github.com/gkstmdahr/4Dir/discussions

[Plus]
  Site web (guide avec images) : https://4dir.net
  Images de chaque écran : dossier Guide\Français
  4Dir est gratuit et open source (GPL-3.0). Les licences de Python, PySide6 (Qt) et pywin32 inclus sont dans le dossier licenses.

{others}
"""

TEXT["pt_BR"] = r"""4Dir v{ver} — gerenciador de arquivos gratuito para Windows 10/11 com vários painéis (até 20) e abas

[Instalação]
  0. (Se você baixou) Antes de extrair: clique com o botão direito no zip > Propriedades > marque 'Desbloquear' embaixo > OK.
     Senão, o Windows mostra um aviso de segurança toda vez que você abrir o 4Dir.
     (Já extraiu? Botão direito em 4Dir.exe e 4Dir.vbs > Propriedades > marque 'Desbloquear'.)
  1. Copie esta pasta para onde quiser (ex.: D:\Tools\4Dir). Não há instalador.
     (Não execute direto de uma unidade de rede: copie para o seu PC.)
  2. Clique duas vezes em 4Dir.exe. Não precisa instalar Python (ele está na pasta runtime).
     (Se o 4Dir.exe for bloqueado pela segurança do Windows (SmartScreen) ou pelo antivírus, use o 4Dir.vbs: faz a mesma coisa.
      Se aparecer a janela do SmartScreen: 'Mais informações' > 'Executar assim mesmo'.)
  3. Atalho na área de trabalho: botão direito em 4Dir.exe > Enviar para > Área de trabalho (criar atalho).
  Desinstalar: apague esta pasta. Nada fica no registro nem no sistema.

[Principais funções]
  - Ícones de layout no topo: 1 / 2 / 3 / 4 / 6 painéis, botão de grade = personalizado (colunas x linhas, até 5 x 4)
  - Abas em cada painel: Ctrl+T nova aba, Ctrl+W fechar, Ctrl+Shift+T reabrir aba fechada, clique do meio = nova aba / fechar
  - Pesquisar em tudo: Ctrl+Shift+F (pesquisa por nome em todas as unidades; o índice leva alguns minutos na primeira vez)
    O que é pesquisado: Ferramentas > Escopo da pesquisa (discos externos, rede e Google Drive precisam ser ativados ali)
  - Favoritos: arraste uma pasta para a barra de favoritos / botão direito na pasta > ★ Adicionar aos favoritos do 4Dir / Ctrl+D
    Favoritos > Organizar favoritos: apagar vários de uma vez, reordenar, agrupar (como pastas), encontrar pastas que não existem mais
  - Arrastar abas: esquerda/direita na barra = reordenar, soltar em outro painel = mover para lá, soltar fora do 4Dir = nova janela
  - Renomear em lote: selecione vários itens e pressione F2 (ou Ferramentas > Renomear em lote) / Ctrl+Z = desfazer a última operação
  - Filtro rápido: Ctrl+F (filtrar a pasta atual por nome)
  - Copiar para o outro painel F6, mover Shift+F6 (para o painel usado logo antes)
  - Ícones de controle de versão: o SVN é mostrado pelo próprio 4Dir; Git, Perforce etc. mostram os ícones das ferramentas instaladas no PC (TortoiseGit, P4EXP...)
    Se não aparecerem: Ferramentas > Ordem dos ícones de sobreposição (Windows) (o Windows usa só os 11 primeiros)
  - Os modos de ícones (pequenos / médios / grandes) mostram prévia das imagens (desligar: Exibir > Mostrar > Pré-visualização de imagens (modos de ícones))
  - Menu Exibir: detalhes/ícones, itens ocultos, extensões de nomes de arquivos, botões de caminho, tema (sistema/claro/escuro), cores, sempre visível, CPU/GPU
  - Exibir > Idioma (Language): 16 idiomas. Padrão = idioma de exibição do Windows. Aplicado ao reiniciar o 4Dir.
    As traduções ficam em bin\lang\<idioma>.json e podem ser editadas no Bloco de Notas.
  - Salvar/carregar janelas: salvar o layout das abas com um nome / recuperar do registro automático após um fechamento inesperado
  - Ferramentas > Explorer Check (diagnóstico do Explorador): encontra e corrige a causa quando o Explorador do Windows está lento
    (Se o próprio 4Dir não abrir, execute diretamente bin\탐색기 점검.vbs, que é o Explorer Check.)

[Se algo der errado]
  Ferramentas > 'Salvar log para relatar problema' cria um zip na pasta 'reports' do 4Dir e mostra para você. Envie esse arquivo.
  (Se o 4Dir não abrir de jeito nenhum, envie a pasta bin\log inteira.)
  Contato: support@4dir.net / Fórum: https://github.com/gkstmdahr/4Dir/discussions

[Mais]
  Site (guia com imagens): https://4dir.net
  Imagens de cada tela: pasta Guide\Português
  O 4Dir é gratuito e de código aberto (GPL-3.0). As licenças do Python, PySide6 (Qt) e pywin32 incluídos estão na pasta licenses.

{others}
"""

TEXT["ru"] = r"""4Dir v{ver} — бесплатный файловый менеджер для Windows 10/11 с несколькими панелями (до 20) и вкладками

[Установка]
  0. (Если скачали из интернета) Перед распаковкой: правый щелчок по zip > Свойства > внизу отметьте 'Разблокировать' > ОК.
     Иначе Windows будет показывать предупреждение безопасности при каждом запуске 4Dir.
     (Уже распаковали? Правый щелчок по 4Dir.exe и 4Dir.vbs > Свойства > отметьте 'Разблокировать'.)
  1. Скопируйте эту папку куда угодно (например, D:\Tools\4Dir). Установка не нужна.
     (Не запускайте прямо с сетевого диска - скопируйте на свой ПК.)
  2. Дважды щёлкните 4Dir.exe. Устанавливать Python не нужно (он в папке runtime).
     (Если 4Dir.exe блокирует защита Windows (SmartScreen) или антивирус, запустите 4Dir.vbs - он делает то же самое.
      Если появилось окно SmartScreen: 'Подробнее' > 'Выполнить в любом случае'.)
  3. Ярлык на рабочем столе: правый щелчок по 4Dir.exe > Отправить > Рабочий стол (создать ярлык).
  Удаление: удалите эту папку. В реестре и системе ничего не остаётся.

[Основные функции]
  - Значки раскладки вверху: 1 / 2 / 3 / 4 / 6 панелей, кнопка сетки = своя раскладка (столбцы x строки, до 5 x 4)
  - Вкладки в каждой панели: Ctrl+T новая вкладка, Ctrl+W закрыть, Ctrl+Shift+T вернуть закрытую, средняя кнопка мыши = новая вкладка / закрыть
  - Поиск везде: Ctrl+Shift+F (поиск по именам файлов на всех дисках; первое построение индекса занимает несколько минут)
    Где искать: Сервис > Область поиска (внешние диски, сеть и Google Диск нужно включить там)
  - Избранное: перетащите папку на панель избранного / правый щелчок по папке > ★ Добавить в избранное 4Dir / Ctrl+D
    Избранное > Упорядочить избранное: удалить сразу несколько, изменить порядок, сгруппировать (как папки), найти исчезнувшие папки
  - Перетаскивание вкладок: влево/вправо в строке вкладок = порядок, на другую панель = переместить туда, за пределы 4Dir = новое окно
  - Пакетное переименование: выделите несколько и нажмите F2 (или Сервис > Пакетное переименование) / Ctrl+Z = отменить последнее действие
  - Быстрый фильтр: Ctrl+F (фильтр текущей папки по имени)
  - Копировать в другую панель F6, переместить Shift+F6 (в панель, где вы были перед этим)
  - Значки систем контроля версий: SVN показывает сам 4Dir; Git, Perforce и др. - значки установленных на ПК программ (TortoiseGit, P4EXP ...)
    Если значков нет: Сервис > Порядок значков-наложений (Windows) (Windows использует только первые 11)
  - В режимах значков (мелкие / обычные / крупные) показываются миниатюры изображений (отключить: Вид > Показать > Миниатюры изображений (режим значков))
  - Меню Вид: таблица/значки, скрытые элементы, расширения имён файлов, кнопки пути, тема (системная/светлая/тёмная), цвета, поверх всех окон, CPU/GPU
  - Вид > Язык (Language): 16 языков. По умолчанию - язык интерфейса Windows. Применяется после перезапуска 4Dir.
    Переводы лежат в bin\lang\<язык>.json, их можно править в Блокноте.
  - Сохранить/загрузить окна: сохранить текущую раскладку вкладок под именем / восстановить из автозаписи после сбоя
  - Сервис > Explorer Check (проверка Проводника): находит и устраняет причину, если Проводник Windows тормозит
    (Если сам 4Dir не открывается, запустите напрямую bin\탐색기 점검.vbs - это Explorer Check.)

[Если что-то не так]
  Сервис > 'Сохранить журнал для отчёта о проблеме' создаёт zip в папке 'reports' внутри 4Dir и показывает его. Пришлите этот файл.
  (Если 4Dir совсем не открывается, пришлите всю папку bin\log.)
  Связь: support@4dir.net / Форум: https://github.com/gkstmdahr/4Dir/discussions

[Ещё]
  Сайт (инструкция с картинками): https://4dir.net
  Картинки каждого окна: папка Guide\Русский
  4Dir бесплатный, с открытым исходным кодом (GPL-3.0). Лицензии входящих в комплект Python, PySide6 (Qt) и pywin32 - в папке licenses.

{others}
"""


def others_block():
    """맨 아래 공통 목록: 다른 언어 사용법 파일 (각 언어 이름은 그 언어로)"""
    lines = ["[Other languages / 다른 언어 / 他の言語 / 其他语言]"]
    for _, fn, name in FILES:
        lines.append(f"  {name} - {fn}")   # 1.0.1: 칸 맞춤 빼냄(한자·한글은 폭이 달라 어긋남)
    return "\n".join(lines)
