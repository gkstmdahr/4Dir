# Fix or improve a 4Dir translation

4Dir's translations were made with machine translation, so some words may sound unnatural.
If you speak one of the languages, you can fix it — no programming needed.

## 1. Try your fix in 4Dir first

1. Open **Settings ▸ General** and click **Fix translation…** next to the language list.
2. 4Dir copies the current language file (for example `de.json`) into your own translation folder and opens it.
3. Open that file in Notepad and change only the text on the **right** side of each line.
   ```
   "이름": "Name",
   ```
   The left side is the Korean original (the key) — don't change it.
4. Save (UTF-8) and restart 4Dir. Your text is used right away and stays after updates.

Rules: keep `{0}`, `{1}`, `%s`, `<b>…</b>` and `\n` (line break) exactly as they are.

## 2. Send it to us

Pick whichever is easier:

- **Issue (easiest):** [open an issue](https://github.com/gkstmdahr/4Dir/issues/new) titled `Translation: <language>` and attach your edited `.json` file (or paste the lines you changed).
- **Pull request:** edit the file in [`bin/lang`](https://github.com/gkstmdahr/4Dir/tree/main/bin/lang) on GitHub and open a pull request.

Your fix will be included in the next version, and you'll be thanked in the release notes (if you like).

---

## 번역 고치기 (한국어 요약)

1. 설정 ▸ 일반 ▸ 언어 옆 **번역 고치기…** → 내 번역 폴더에 지금 언어 파일이 복사되고 폴더가 열림
2. 메모장으로 오른쪽 글자만 고치고(왼쪽 한국어 원문은 그대로) 저장 → 4Dir 다시 시작하면 바로 적용 (업데이트해도 남음)
3. 고친 파일을 [이슈](https://github.com/gkstmdahr/4Dir/issues/new)에 첨부하거나 [`bin/lang`](https://github.com/gkstmdahr/4Dir/tree/main/bin/lang) 에 PR 로 보내 주시면 다음 버전에 넣습니다.
