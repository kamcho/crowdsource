(function () {
    var modal = document.getElementById('whatsappMessageModal');
    if (!modal) return;

    var metadata = document.getElementById('whatsappMessageMetadata');
    var body = document.getElementById('whatsappMessageBody');
    var error = document.getElementById('whatsappMessageError');
    var fields = [
        ['display_name', 'Customer'],
        ['phone', 'WhatsApp number'],
        ['direction', 'Direction'],
        ['sent_at', 'Sent at'],
        ['message_id', 'Meta message ID'],
        ['message_type', 'Message type'],
        ['media_id', 'Media ID'],
        ['media_mime_type', 'Media MIME type'],
        ['delivery_status', 'Delivery status'],
        ['status_detail', 'Status details'],
        ['status_updated_at', 'Status updated'],
        ['sender_name', 'WhatsApp profile name'],
        ['tenant', 'Tenant']
    ];

    document.addEventListener('click', function (event) {
        var button = event.target.closest('.whatsapp-message-open');
        if (!button) return;

        error.hidden = true;
        error.textContent = '';
        metadata.replaceChildren();
        body.textContent = 'Loading…';
        modal.showModal();

        fetch(button.dataset.detailUrl, {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin'
        })
            .then(function (response) {
                if (!response.ok) throw new Error('Could not load message details.');
                return response.json();
            })
            .then(function (data) {
                metadata.replaceChildren();
                fields.forEach(function (field) {
                    if (!data[field[0]]) return;
                    var term = document.createElement('dt');
                    var value = document.createElement('dd');
                    term.textContent = field[1];
                    value.textContent = data[field[0]];
                    metadata.append(term, value);
                });
                body.textContent = data.body || '(No text content)';
            })
            .catch(function (exception) {
                body.textContent = '';
                error.textContent = exception.message;
                error.hidden = false;
            });
    });
})();
