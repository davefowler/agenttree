/**
 * Shared WebRTC voice session logic for OpenAI Realtime API.
 *
 * Usage:
 *   const session = new VoiceSession({
 *     onStatus(text, state)  — called with state: 'idle' | 'connecting' | 'active' | 'error'
 *     onLog(text, className) — called for log messages (className may be 'tool-call')
 *     getIssueId()           — return current issue ID or null
 *   });
 *   session.toggle();  // start or stop
 *   session.stop();    // force stop
 */

class VoiceSession {
    constructor(opts) {
        this.onStatus = opts.onStatus || function() {};
        this.onLog = opts.onLog || function() {};
        this.getIssueId = opts.getIssueId || function() { return null; };

        this.pc = null;
        this.dc = null;
        this.audioEl = null;
        this.localStream = null;
        this.active = false;
    }

    async toggle() {
        if (this.pc) {
            this.stop();
        } else {
            await this.start();
        }
    }

    async start() {
        this.onStatus('Connecting...', 'connecting');

        try {
            // 1. Get ephemeral token from our server
            var issueId = this.getIssueId();
            var tokenUrl = '/api/voice/token' + (issueId ? '?issue=' + issueId : '');
            var tokenResp = await fetch(tokenUrl);
            if (!tokenResp.ok) {
                var err = await tokenResp.json();
                throw new Error(err.detail || 'Token request failed');
            }
            var tokenData = await tokenResp.json();
            var ephemeralKey = tokenData.client_secret && tokenData.client_secret.value;
            if (!ephemeralKey) throw new Error('No ephemeral key in response');

            // 2. Create peer connection
            this.pc = new RTCPeerConnection();

            // 3. Set up remote audio playback
            this.audioEl = document.createElement('audio');
            this.audioEl.autoplay = true;
            var self = this;
            this.pc.ontrack = function(e) { self.audioEl.srcObject = e.streams[0]; };

            // 4. Get microphone and add track
            this.localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.pc.addTrack(this.localStream.getTracks()[0]);

            // 5. Create data channel for events
            this.dc = this.pc.createDataChannel('oai-events');
            this.dc.onopen = function() { self.onLog('Data channel open'); };
            this.dc.onmessage = function(e) { self._onDataChannelMessage(e); };

            // 6. SDP offer/answer exchange via OpenAI Realtime API GA endpoints
            //    (Dec 2025 — replaced beta /v1/realtime/sessions)
            var offer = await this.pc.createOffer();
            await this.pc.setLocalDescription(offer);

            var sdpResp = await fetch('https://api.openai.com/v1/realtime/calls?model=gpt-realtime', {
                method: 'POST',
                body: offer.sdp,
                headers: {
                    'Authorization': 'Bearer ' + ephemeralKey,
                    'Content-Type': 'application/sdp',
                },
            });

            if (!sdpResp.ok) throw new Error('SDP exchange failed: ' + sdpResp.status);

            var answerSdp = await sdpResp.text();
            await this.pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

            this.pc.onconnectionstatechange = function() {
                if (!self.pc) return;
                if (self.pc.connectionState === 'connected') {
                    self.active = true;
                    self.onStatus('Connected — speak naturally', 'active');
                    self.onLog('Session started');
                } else if (self.pc.connectionState === 'failed' || self.pc.connectionState === 'disconnected') {
                    self.stop();
                    self.onStatus('Connection lost', 'error');
                }
            };

            if (issueId) {
                this.onLog('Context: issue #' + issueId);
            }

            // Keep screen awake
            if ('wakeLock' in navigator) {
                try { await navigator.wakeLock.request('screen'); } catch(e) {}
            }

        } catch (err) {
            this.onStatus('Error: ' + err.message, 'error');
            this.onLog('Error: ' + err.message);
            this.stop();
        }
    }

    stop() {
        if (this.dc) { try { this.dc.close(); } catch(e) {} this.dc = null; }
        if (this.localStream) {
            this.localStream.getTracks().forEach(function(t) { t.stop(); });
            this.localStream = null;
        }
        if (this.pc) {
            this.pc.getSenders().forEach(function(s) { if (s.track) s.track.stop(); });
            try { this.pc.close(); } catch(e) {}
            this.pc = null;
        }
        if (this.audioEl) { this.audioEl.srcObject = null; this.audioEl = null; }
        this.active = false;
        this.onStatus('Tap to start a voice session', 'idle');
        this.onLog('Session ended');
    }

    _onDataChannelMessage(e) {
        var event = JSON.parse(e.data);
        if (event.type === 'response.done' && event.response && event.response.output) {
            var self = this;
            event.response.output.forEach(function(output) {
                if (output.type === 'function_call') {
                    self._handleToolCall(output);
                }
            });
        }
    }

    async _handleToolCall(output) {
        var fnName = output.name;
        var fnArgs;
        try { fnArgs = JSON.parse(output.arguments || '{}'); } catch(e) { fnArgs = {}; }
        this.onLog('Tool: ' + fnName + '(' + JSON.stringify(fnArgs) + ')', 'tool-call');

        try {
            var resp = await fetch('/api/voice/tool-call', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: fnName, arguments: fnArgs }),
            });
            var data = await resp.json();
            var result = data.result || 'No result';

            // Send result back to OpenAI via data channel
            if (this.dc && this.dc.readyState === 'open') {
                this.dc.send(JSON.stringify({
                    type: 'conversation.item.create',
                    item: {
                        type: 'function_call_output',
                        call_id: output.call_id,
                        output: result,
                    },
                }));
                this.dc.send(JSON.stringify({ type: 'response.create' }));
            }

            this.onLog('Done: ' + (result.length > 100 ? result.substring(0, 100) + '...' : result), 'tool-call');
        } catch (err) {
            this.onLog('Tool error: ' + err.message, 'tool-call');
        }
    }
}
