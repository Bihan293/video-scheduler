ФАЙЛЫ ДЛЯ GITHUB PAGES — VIDEO SCHEDULER

Перед публикацией:
1) Замени [ADD A CONTACT EMAIL BEFORE PUBLISHING] в terms.html и privacy.html на рабочий email.
2) Это шаблоны. Они должны соответствовать реальной работе проекта и не гарантируют одобрение TikTok.
3) Эти страницы не создают OAuth callback и не включают API.

КОМАНДЫ TERMUX:
pkg update -y
pkg install git unzip -y
termux-setup-storage

Скачай ZIP на телефон. Если он лежит в Downloads:
cd ~
unzip ~/storage/downloads/video-scheduler-pages.zip
cd ~/video-scheduler-pages

Создай публичный репозиторий на https://github.com/new с названием video-scheduler. Не добавляй README, license или .gitignore при создании.

Затем выполни в папке проекта (замени YOUR_GITHUB_USERNAME своим логином):
git init
git branch -M main
git add index.html terms.html privacy.html README_RU.txt
git commit -m "Add Video Scheduler policy pages"
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/video-scheduler.git
git push -u origin main

Если GitHub запросит пароль, обычный пароль аккаунта может не подойти. Авторизуйся через браузер или используй GitHub token; не отправляй токен в чат и не помещай его в публичные файлы.

ВКЛЮЧИ PAGES:
1. Открой репозиторий → Settings → Pages.
2. В Build and deployment выбери Deploy from a branch.
3. Branch: main; folder: /(root); нажми Save.
4. Подожди публикации.

URL будут иметь вид:
https://YOUR_GITHUB_USERNAME.github.io/video-scheduler/
https://YOUR_GITHUB_USERNAME.github.io/video-scheduler/terms.html
https://YOUR_GITHUB_USERNAME.github.io/video-scheduler/privacy.html

Замени YOUR_GITHUB_USERNAME своим логином и используй URL только после проверки, что страницы открываются.
