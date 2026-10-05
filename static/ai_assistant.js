// AI-ассистент для Mystical (локальный анализ)
(function() {
    var modal = null;
    var currentPostId = null;

    function createModal() {
        var div = document.createElement('div');
        div.className = 'ai-modal';
        div.id = 'ai-modal';
        div.innerHTML = `
            <div class="ai-modal-overlay" onclick="closeAIAssistant()"></div>
            <div class="ai-modal-content">
                <div class="ai-modal-header">
                    <h3>🤖 AI-ассистент</h3>
                    <button class="ai-modal-close" onclick="closeAIAssistant()">×</button>
                </div>
                <div class="ai-modal-body">
                    <div class="ai-actions">
                        <button class="ai-action-btn" data-action="analyze">📊 Анализ</button>
                        <button class="ai-action-btn" data-action="summarize">📝 Суммаризировать</button>
                        <button class="ai-action-btn" data-action="keywords">🔤 Ключевые слова</button>
                        <button class="ai-action-btn" data-action="advice">💡 Совет</button>
                    </div>
                    <div class="ai-result" id="ai-result">
                        <p class="ai-hint">Выбери действие выше, чтобы AI проанализировал пост</p>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(div);

        // Обработка клика на действия
        div.addEventListener('click', function(e) {
            var btn = e.target.closest('.ai-action-btn');
            if (btn) {
                var action = btn.getAttribute('data-action');
                runAction(action);
            }
        });

        return div;
    }

    function runAction(action) {
        var post = document.getElementById('post-' + currentPostId);
        if (!post) {
            // Ищем пост по data-id
            post = document.querySelector(`[data-post-id="${currentPostId}"]`);
        }

        // Берём текст поста из .post-content
        var postElement = document.querySelector(`.post[data-id="${currentPostId}"]`) ||
                          document.querySelector(`#post-${currentPostId}`);
        var text = '';
        if (postElement) {
            var contentEl = postElement.querySelector('.post-content');
            if (contentEl) text = contentEl.textContent.trim();
        }

        // Если не нашли — ищем в текущей странице
        if (!text) {
            var allPosts = document.querySelectorAll('.post-content');
            if (allPosts.length > 0) text = allPosts[0].textContent.trim();
        }

        if (!text) {
            showResult('⚠️ Не удалось найти текст поста');
            return;
        }

        showResult('⏳ AI думает...');

        fetch('/ai_analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, action: action })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                var html = '<div class="ai-result-title">' + escapeHtml(data.title || '') + '</div>';
                html += '<div class="ai-result-text">' + escapeHtml(data.text || '').replace(/\\n/g, '<br>') + '</div>';
                showResult(html, true);
            } else {
                showResult('⚠️ ' + (data.error || 'Ошибка'));
            }
        })
        .catch(function(err) {
            showResult('⚠️ Ошибка сети: ' + err.message);
        });
    }

    function showResult(content, isHtml) {
        var result = document.getElementById('ai-result');
        if (!result) return;
        if (isHtml) {
            result.innerHTML = content;
        } else {
            result.innerHTML = '<p class="ai-hint">' + escapeHtml(content) + '</p>';
        }
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    window.openAIAssistant = function(postId) {
        currentPostId = postId;
        if (!modal) modal = createModal();
        modal.classList.add('active');
        showResult('Выбери действие выше, чтобы AI проанализировал пост');
    };

    window.closeAIAssistant = function() {
        if (modal) modal.classList.remove('active');
    };
})();
