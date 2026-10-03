// Голосовые комментарии для Mystical (MP4 для Safari)
(function() {
    var mediaRecorder = null;
    var audioChunks = [];
    var recordingStartTime = 0;
    var recordingTimerInterval = null;
    var currentButton = null;
    var MAX_DURATION = 60;
    var currentMimeType = 'audio/mp4';

    window.toggleVoiceRecording = function(button, targetType, targetId) {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            stopRecording();
            return;
        }
        startRecording(button, targetType, targetId);
    };

    function startRecording(button, targetType, targetId) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert('Твой браузер не поддерживает запись звука');
            return;
        }

        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(function(stream) {
                audioChunks = [];

                // Выбираем формат: MP4 (для Safari) или WebM
                var options = {};
                if (typeof MediaRecorder.isTypeSupported === 'function') {
                    if (MediaRecorder.isTypeSupported('audio/mp4')) {
                        options = { mimeType: 'audio/mp4' };
                        currentMimeType = 'audio/mp4';
                    } else if (MediaRecorder.isTypeSupported('audio/mp4;codecs=mp4a')) {
                        options = { mimeType: 'audio/mp4;codecs=mp4a' };
                        currentMimeType = 'audio/mp4';
                    } else if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
                        options = { mimeType: 'audio/webm;codecs=opus' };
                        currentMimeType = 'audio/webm';
                    } else {
                        options = {};
                        currentMimeType = 'audio/webm';
                    }
                }

                try {
                    mediaRecorder = new MediaRecorder(stream, options);
                } catch (e) {
                    mediaRecorder = new MediaRecorder(stream);
                    currentMimeType = mediaRecorder.mimeType || 'audio/webm';
                }

                currentButton = button;

                mediaRecorder.ondataavailable = function(e) {
                    if (e.data.size > 0) audioChunks.push(e.data);
                };

                mediaRecorder.onstop = function() {
                    var blobType = mediaRecorder.mimeType || currentMimeType;
                    var blob = new Blob(audioChunks, { type: blobType });
                    var duration = Math.round((Date.now() - recordingStartTime) / 1000);

                    stream.getTracks().forEach(function(t) { t.stop(); });
                    uploadAudio(blob, duration, targetType, targetId, blobType);
                };

                mediaRecorder.start();
                recordingStartTime = Date.now();

                button.classList.add('recording');
                button.textContent = '⏹ 0:00';

                recordingTimerInterval = setInterval(function() {
                    var sec = Math.round((Date.now() - recordingStartTime) / 1000);
                    var mm = Math.floor(sec / 60);
                    var ss = sec % 60;
                    button.textContent = '⏹ ' + mm + ':' + String(ss).padStart(2, '0');

                    if (sec >= MAX_DURATION) stopRecording();
                }, 200);
            })
            .catch(function(err) {
                alert('Не удалось получить доступ к микрофону: ' + err.message);
            });
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
        if (recordingTimerInterval) {
            clearInterval(recordingTimerInterval);
            recordingTimerInterval = null;
        }
        if (currentButton) {
            currentButton.classList.remove('recording');
            currentButton.textContent = '🎤';
            currentButton = null;
        }
    }

    function uploadAudio(blob, duration, targetType, targetId, mimeType) {
        // Определяем расширение по mimeType
        var ext = 'mp4';
        if (mimeType && mimeType.indexOf('webm') !== -1) ext = 'webm';
        else if (mimeType && mimeType.indexOf('ogg') !== -1) ext = 'ogg';

        var filename = 'voice_' + Date.now() + '.' + ext;

        var formData = new FormData();
        formData.append('audio', blob, filename);
        formData.append('duration', duration);

        var url = '/upload_audio/' + targetType + '/' + targetId;

        fetch(url, {
            method: 'POST',
            body: formData
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                location.reload();
            } else {
                alert('Ошибка: ' + (data.error || 'неизвестно'));
            }
        })
        .catch(function(err) {
            alert('Ошибка отправки: ' + err.message);
        });
    }
})();
