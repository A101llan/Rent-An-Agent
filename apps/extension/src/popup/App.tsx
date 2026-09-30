import { useState, useEffect, useRef } from 'react';
import { MessageSquare, Bot, Loader2, AlertCircle, Send, Unplug, ChevronRight } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = 'http://localhost:8000';

interface Message {
  role: 'user' | 'agent' | 'system';
  content: string;
  approval_id?: string;
}

interface AgentInfo {
  agent_name: string;
  agent_slug: string;
  session_id: string;
  expires_at: string;
}

interface OnboardingQuestion {
  id: string;
  question: string;
  placeholder: string;
}

type AppState = 'login' | 'connecting' | 'onboarding' | 'chat' | 'error';

export default function App() {
  const [state, setState] = useState<AppState>('login');
  const [token, setToken] = useState('');
  const [agentInfo, setAgentInfo] = useState<AgentInfo | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [questions, setQuestions] = useState<OnboardingQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [isSubmittingOnboarding, setIsSubmittingOnboarding] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load saved token on mount
  useEffect(() => {
    chrome.storage.local.get(['embed_token'], (result) => {
      if (result.embed_token) {
        setToken(result.embed_token);
        authenticate(result.embed_token);
      }
    });
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function authenticate(rawToken: string) {
    setState('connecting');
    setErrorMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/v1/embed/bootstrap`, {
        headers: { 'Authorization': `Bearer ${rawToken}` }
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: { error: { message: 'Invalid token' } } }));
        const msg = err?.detail?.error?.message || err?.detail || 'Authentication failed';
        throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
      }

      const data = await res.json();
      const info: AgentInfo = {
        agent_name: data.agent_name,
        agent_slug: data.agent_slug,
        session_id: data.session_id,
        expires_at: data.expires_at,
      };
      setAgentInfo(info);

      // Save valid token
      chrome.storage.local.set({ embed_token: rawToken });

      if (!data.onboarding_complete) {
        // Need to answer onboarding questions first
        setQuestions(data.questions || []);
        setAnswers({});
        setState('onboarding');
      } else {
        // Already onboarded — go straight to chat
        setMessages([{
          role: 'agent',
          content: data.welcome_message || `Hi! I'm ${data.agent_name}. How can I help you today?`
        }]);
        setState('chat');
      }
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : 'Connection failed');
      setState('error');
    }
  }

  async function submitOnboarding() {
    // Validate all questions answered
    const missing = questions.filter(q => !answers[q.id]?.trim());
    if (missing.length > 0) return;

    setIsSubmittingOnboarding(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/embed/onboarding`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ answers }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = err?.detail?.error?.message || 'Onboarding failed';
        throw new Error(msg);
      }

      const data = await res.json();
      setMessages([{
        role: 'agent',
        content: data.welcome_message || `Hi! I'm ${agentInfo?.agent_name}. How can I help you today?`
      }]);
      setState('chat');
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : 'Onboarding failed');
      setState('error');
    } finally {
      setIsSubmittingOnboarding(false);
    }
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isSending) return;

    setInput('');
    setIsSending(true);
    setMessages(prev => [...prev, { role: 'user', content: text }]);

    // Try WebSocket streaming first
    try {
      const wsUrl = `ws://localhost:8000/api/v1/embed/ws/${token}`;
      const ws = new WebSocket(wsUrl);

      let streamingIndex: number | null = null;

      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          ws.close();
          reject(new Error("WebSocket timeout, falling back to HTTP"));
        }, 3000);

        ws.onopen = () => {
          clearTimeout(timeout);
          // Add empty agent message for streaming
          setMessages(prev => {
            streamingIndex = prev.length;
            return [...prev, { role: 'agent', content: '' }];
          });
          ws.send(text);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'chunk') {
              setMessages(prev => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last && last.role === 'agent') {
                  next[next.length - 1] = { ...last, content: last.content + data.content };
                }
                return next;
              });
            } else if (data.type === 'end') {
              ws.close();
              resolve();
            } else if (data.type === 'error') {
              ws.close();
              reject(new Error(data.message));
            }
          } catch {
            // Ignore non-json
          }
        };

        ws.onerror = () => {
          clearTimeout(timeout);
          reject(new Error("WebSocket error"));
        };
      });
      setIsSending(false);
      return;
    } catch {
      // WebSocket failed or timed out — fallback to HTTP POST below
    }

    // Fallback: HTTP POST
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const context = {
        url: tab?.url || '',
        title: tab?.title || '',
      };

      const res = await fetch(`${API_BASE}/api/v1/embed/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ message: text, context }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = err?.detail?.error?.message || err?.detail || 'Agent error';
        throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
      }

      const data = await res.json();
      setMessages(prev => [...prev, { 
        role: 'agent', 
        content: data.reply,
        approval_id: data.approval_id
      }]);
    } catch (e: unknown) {
      setMessages(prev => [...prev, {
        role: 'system',
        content: `Error: ${e instanceof Error ? e.message : 'Unknown error'}`
      }]);
    } finally {
      setIsSending(false);
    }
  }

  async function handleApproval(approvalId: string, action: 'approve' | 'reject') {
    // In a real implementation, this would hit an API endpoint like /api/v1/embed/approvals/{id}
    // For now, we simulate the agent's response to the approval/rejection.
    
    // Optimistically remove the approval_id from the message so the card disappears
    setMessages(prev => prev.map(m => 
      m.approval_id === approvalId ? { ...m, approval_id: undefined } : m
    ));
    
    // Simulate action
    setIsSending(true);
    setMessages(prev => [...prev, { role: 'user', content: action === 'approve' ? 'Approved.' : 'Rejected.' }]);
    
    setTimeout(() => {
      setMessages(prev => [...prev, { 
        role: 'agent', 
        content: action === 'approve' 
          ? 'Great, I will proceed with that action now.' 
          : 'Understood, I have cancelled that action.'
      }]);
      setIsSending(false);
    }, 1000);
  }

  function disconnect() {
    chrome.storage.local.remove('embed_token');
    setToken('');
    setAgentInfo(null);
    setMessages([]);
    setQuestions([]);
    setAnswers({});
    setState('login');
  }

  // ─── Render States ─────────────────────────────────────────────────────────

  if (state === 'login') {
    return (
      <div className="flex flex-col h-full bg-slate-950 text-white">
        <Header />
        <div className="flex-1 flex flex-col items-center justify-center p-6 space-y-4">
          <div className="w-14 h-14 rounded-full bg-indigo-600/20 flex items-center justify-center">
            <Bot className="w-7 h-7 text-indigo-400" />
          </div>
          <div className="text-center">
            <h2 className="font-semibold text-lg text-white">Connect Your Agent</h2>
            <p className="text-xs text-slate-400 mt-1">Paste the embed key from your AgentHub session</p>
          </div>
          <input
            type="text"
            placeholder="ahk_live_..."
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && token.trim() && authenticate(token)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <button
            onClick={() => authenticate(token)}
            disabled={!token.trim()}
            className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-medium rounded-lg text-sm transition-colors"
          >
            Connect Agent
          </button>

          <div className="w-full p-3 rounded-lg bg-slate-900/60 border border-slate-800 text-[11px] text-slate-400 space-y-1">
            <p className="font-medium text-slate-300">💡 How to find your key:</p>
            <p>1. Go to your AgentHub active session page</p>
            <p>2. Click <span className="text-indigo-400 font-mono">Copy Embed Key</span></p>
            <p>3. Paste key above to activate live assistant</p>
          </div>
        </div>
      </div>
    );
  }

  if (state === 'connecting') {
    return (
      <div className="flex flex-col h-full bg-slate-950 text-white">
        <Header />
        <div className="flex-1 flex flex-col items-center justify-center space-y-3 text-slate-400">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
          <p className="text-sm">Authenticating with AgentHub...</p>
        </div>
      </div>
    );
  }

  if (state === 'onboarding') {
    const allAnswered = questions.every(q => answers[q.id]?.trim());
    return (
      <div className="flex flex-col h-full bg-slate-950 text-white">
        <Header />
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          <motion.div 
            initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} 
            className="text-center pb-4 border-b border-white/10"
          >
            <div className="w-12 h-12 rounded-full bg-indigo-600/20 flex items-center justify-center mx-auto mb-3 shadow-inner shadow-indigo-500/20">
              <Bot className="w-6 h-6 text-indigo-400" />
            </div>
            <p className="font-bold text-base text-white">{agentInfo?.agent_name}</p>
            <p className="text-xs text-slate-400 mt-1">Answer {questions.length} quick questions to get started</p>
          </motion.div>

          <div className="space-y-4">
            <AnimatePresence>
              {questions.map((q, idx) => (
                <motion.div 
                  key={q.id} 
                  initial={{ opacity: 0, x: -10 }} 
                  animate={{ opacity: 1, x: 0 }} 
                  transition={{ delay: idx * 0.1 }}
                  className="space-y-1.5"
                >
                  <label className="text-xs font-medium text-indigo-200 ml-1">{q.question}</label>
                  <input
                    type="text"
                    placeholder={q.placeholder || "Type your answer..."}
                    value={answers[q.id] || ''}
                    onChange={(e) => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                    className="w-full px-4 py-2.5 bg-slate-900/50 border border-white/10 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 transition-all shadow-inner shadow-black/20"
                  />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </div>

        <div className="p-3 bg-slate-900 border-t border-slate-800">
          <button
            onClick={submitOnboarding}
            disabled={!allAnswered || isSubmittingOnboarding}
            className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-medium rounded-lg text-sm transition-colors flex items-center justify-center space-x-2"
          >
            {isSubmittingOnboarding ? (
              <><Loader2 className="w-4 h-4 animate-spin" /><span>Setting up...</span></>
            ) : (
              <><span>Start Chatting</span><ChevronRight className="w-4 h-4" /></>
            )}
          </button>
        </div>
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div className="flex flex-col h-full bg-slate-950 text-white">
        <Header />
        <motion.div 
          initial={{ opacity: 0, scale: 0.9 }} 
          animate={{ opacity: 1, scale: 1 }} 
          className="flex-1 flex flex-col items-center justify-center p-6 space-y-5 text-center"
        >
          <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center relative">
            <div className="absolute inset-0 rounded-full bg-red-500/5 animate-ping"></div>
            <AlertCircle className="w-8 h-8 text-red-400 relative z-10" />
          </div>
          <div>
            <p className="font-bold text-lg text-red-400">Connection Failed</p>
            <p className="text-sm text-slate-400 mt-2 leading-relaxed bg-slate-900/50 p-3 rounded-xl border border-white/5">{errorMsg}</p>
          </div>
          <div className="flex flex-col space-y-3 w-full max-w-[200px] mt-4">
            <button 
              onClick={() => authenticate(token)} 
              className="w-full py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm font-medium text-white transition-colors"
            >
              Retry Connection
            </button>
            <button 
              onClick={() => setState('login')} 
              className="w-full py-2 bg-transparent text-sm text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              Use a different token
            </button>
          </div>
        </motion.div>
      </div>
    );
  }

  // ─── Chat State ─────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full bg-slate-950 text-white">
      {/* Header with Agent Info */}
      <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-3 bg-slate-900/80 backdrop-blur-md border-b border-white/10">
        <div className="flex items-center space-x-2 min-w-0">
          <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center flex-shrink-0">
            <Bot className="w-4 h-4 text-white" />
          </div>
          <div className="min-w-0 flex flex-col">
            <p className="font-semibold text-sm text-white truncate leading-tight">{agentInfo?.agent_name}</p>
            <div className="flex items-center space-x-2 mt-0.5">
              <div className="flex items-center space-x-1">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400"></span>
                <p className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">Active</p>
              </div>
              {agentInfo?.expires_at && (
                 <ExpiryTimer expiresAt={agentInfo.expires_at} onExpire={disconnect} />
              )}
            </div>
          </div>
        </div>
        <button onClick={disconnect} title="Disconnect" className="text-slate-500 hover:text-red-400 transition-colors ml-2 flex-shrink-0">
          <Unplug className="w-4 h-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <AnimatePresence initial={false}>
          {messages.length === 0 && !isSending && (
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex-1 flex items-center justify-center text-slate-500 text-sm"
            >
              Start a conversation...
            </motion.div>
          )}
          
          {messages.map((msg, i) => (
            <motion.div 
              key={i} 
              initial={{ opacity: 0, y: 10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {msg.role === 'system' ? (
                <p className="text-xs text-yellow-400 text-center w-full">{msg.content}</p>
              ) : (
                <div className={`max-w-[85%] flex flex-col space-y-2`}>
                  <div className={`px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap shadow-sm ${
                    msg.role === 'user'
                      ? 'bg-indigo-600 text-white rounded-br-sm shadow-indigo-500/20'
                      : 'bg-white/10 backdrop-blur-md border border-white/5 text-slate-100 rounded-bl-sm shadow-black/20'
                  }`}>
                    {msg.content}
                  </div>
                  
                  {msg.approval_id && (
                    <motion.div 
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="bg-slate-800/60 backdrop-blur-md border border-indigo-500/30 rounded-xl p-3 shadow-lg shadow-indigo-900/20 self-start w-full"
                    >
                      <p className="text-xs text-slate-300 mb-3">Does this look correct?</p>
                      <div className="flex space-x-2">
                        <button 
                          onClick={() => handleApproval(msg.approval_id!, 'approve')}
                          className="flex-1 bg-indigo-600/90 hover:bg-indigo-500 text-white text-xs font-medium py-1.5 px-3 rounded-lg transition-all hover:shadow-lg hover:shadow-indigo-500/30 active:scale-95"
                        >
                          Accept
                        </button>
                        <button 
                          onClick={() => handleApproval(msg.approval_id!, 'reject')}
                          className="flex-1 bg-slate-700/80 hover:bg-slate-600 text-slate-200 text-xs font-medium py-1.5 px-3 rounded-lg transition-all active:scale-95 border border-white/5"
                        >
                          Reject
                        </button>
                      </div>
                    </motion.div>
                  )}
                </div>
              )}
            </motion.div>
          ))}
          
          {isSending && (
            <motion.div 
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex justify-start"
            >
              <div className="bg-white/5 backdrop-blur-sm border border-white/5 text-slate-400 px-4 py-2 rounded-2xl rounded-bl-sm text-xs flex space-x-1 items-center">
                <motion.div className="w-1.5 h-1.5 bg-indigo-500 rounded-full" animate={{ y: [0, -3, 0] }} transition={{ duration: 0.6, repeat: Infinity, delay: 0 }} />
                <motion.div className="w-1.5 h-1.5 bg-indigo-500 rounded-full" animate={{ y: [0, -3, 0] }} transition={{ duration: 0.6, repeat: Infinity, delay: 0.2 }} />
                <motion.div className="w-1.5 h-1.5 bg-indigo-500 rounded-full" animate={{ y: [0, -3, 0] }} transition={{ duration: 0.6, repeat: Infinity, delay: 0.4 }} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 bg-slate-900 border-t border-slate-800 flex space-x-2">
        <input
          type="text"
          placeholder={`Message ${agentInfo?.agent_name}...`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
          disabled={isSending}
          className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
        />
        <button
          onClick={sendMessage}
          disabled={isSending || !input.trim()}
          className="px-3 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function Header() {
  return (
    <div className="flex items-center space-x-2 px-4 py-3 bg-slate-900 border-b border-slate-800">
      <div className="w-6 h-6 rounded bg-indigo-600 flex items-center justify-center">
        <MessageSquare className="w-3.5 h-3.5 text-white" />
      </div>
      <span className="font-bold text-sm tracking-tight">AgentHub</span>
    </div>
  );
}

function ExpiryTimer({ expiresAt, onExpire }: { expiresAt: string, onExpire: () => void }) {
  const [timeLeft, setTimeLeft] = useState('');

  useEffect(() => {
    const updateTimer = () => {
      const now = new Date().getTime();
      const expiry = new Date(expiresAt).getTime();
      const diff = expiry - now;

      if (diff <= 0) {
        onExpire();
        return;
      }

      const hours = Math.floor(diff / (1000 * 60 * 60));
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      
      if (hours > 0) {
        setTimeLeft(`${hours}h ${minutes}m left`);
      } else {
        setTimeLeft(`${minutes}m left`);
      }
    };

    updateTimer();
    const interval = setInterval(updateTimer, 60000); // update every minute
    return () => clearInterval(interval);
  }, [expiresAt, onExpire]);

  return (
    <p className="text-[10px] text-slate-500 font-medium tracking-wide">
      • {timeLeft}
    </p>
  );
}
