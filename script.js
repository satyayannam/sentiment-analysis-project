const recordButton = document.getElementById('record');
const stopButton = document.getElementById('stop');
const timerDisplay = document.getElementById('timer');

let mediaRecorder;
let audioChunks = [];

recordButton.addEventListener('click', async () => {
    audioChunks = [];
    timerDisplay.textContent = "Recording...";

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.start();

        mediaRecorder.ondataavailable = e => {
            audioChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
            timerDisplay.textContent = "Processing...";

            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
            const formData = new FormData();
            formData.append('audio_data', audioBlob, 'recorded_audio.wav');

            try {
                // Start the page reload after 2 seconds
                setTimeout(() => location.reload(), 1000);
                
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    timerDisplay.textContent = "Upload complete!";
                } else {
                    throw new Error("Upload failed");
                }
            } catch (error) {
                console.error('Error uploading:', error);
                timerDisplay.textContent = "Upload failed!";
                // Note: User might not see this message if the page reloads before error occurs
            }
        };

        recordButton.disabled = true;
        stopButton.disabled = false;
    } catch (error) {
        console.error('Mic access error:', error);
        alert("Microphone access denied!");
    }
});

stopButton.addEventListener('click', () => {
    if (mediaRecorder) {
        mediaRecorder.stop();
    }
    recordButton.disabled = false;
    stopButton.disabled = true;
});