/**
 * Shared panel resize functionality.
 * Used by agent_chat_panel.html and manager_panel.html.
 */
function initPanelResize(panel, storageKey, defaultWidth) {
    var handle = panel.querySelector('.resize-handle');
    if (!handle) return;

    var minWidth = 250;
    var maxWidth = 800;
    var isDragging = false;

    // Restore saved width on load
    var savedWidth = localStorage.getItem(storageKey);
    if (savedWidth) {
        var width = Math.min(Math.max(parseInt(savedWidth, 10), minWidth), Math.min(maxWidth, window.innerWidth * 0.6));
        panel.style.width = width + 'px';
    }

    handle.addEventListener('mousedown', function(e) {
        e.preventDefault();
        isDragging = true;
        handle.classList.add('dragging');
        panel.style.transition = 'none';
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        var maxAllowed = Math.min(maxWidth, window.innerWidth * 0.6);
        var newWidth = Math.min(Math.max(window.innerWidth - e.clientX, minWidth), maxAllowed);
        panel.style.width = newWidth + 'px';
    });

    document.addEventListener('mouseup', function() {
        if (!isDragging) return;
        isDragging = false;
        handle.classList.remove('dragging');
        panel.style.transition = '';
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        localStorage.setItem(storageKey, parseInt(panel.style.width, 10));
    });
}
