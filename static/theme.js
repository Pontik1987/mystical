// 🌙 Тёмная тема для Mystical
(function() {
    // Проверяем сохранённую тему при загрузке
    var savedTheme = localStorage.getItem('mystical-theme');
    if (savedTheme === 'dark') {
        document.documentElement.classList.add('dark-preload');
        document.addEventListener('DOMContentLoaded', function() {
            document.body.classList.add('dark');
            document.documentElement.classList.remove('dark-preload');
            updateButton();
        });
    } else {
        document.addEventListener('DOMContentLoaded', function() {
            updateButton();
        });
    }

    // Функция обновления иконки кнопки
    function updateButton() {
        var buttons = document.querySelectorAll('.theme-toggle');
        buttons.forEach(function(btn) {
            if (document.body.classList.contains('dark')) {
                btn.textContent = '☀️';
                btn.title = 'Светлая тема';
            } else {
                btn.textContent = '🌙';
                btn.title = 'Тёмная тема';
            }
        });
    }

    // Функция переключения
    window.toggleTheme = function() {
        document.body.classList.toggle('dark');
        var isDark = document.body.classList.contains('dark');
        localStorage.setItem('mystical-theme', isDark ? 'dark' : 'light');
        updateButton();
    };
})();
