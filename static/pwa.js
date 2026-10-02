// Регистрация Service Worker для PWA
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(function(reg) {
                console.log('✅ Service Worker зарегистрирован:', reg.scope);
            })
            .catch(function(err) {
                console.log('❌ Service Worker не зарегистрирован:', err);
            });
    });
}
