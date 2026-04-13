/* ── ScorPred — Magic UI Interactions ───────────────────────────────────────── */

/* Guard: only run when GSAP is available */
if (typeof gsap !== 'undefined') {

  gsap.registerPlugin(ScrollTrigger);

  /* ── Card entrance animations ─────────────────────────────────────────────── */
  gsap.utils.toArray('.glow-card').forEach((card, i) => {
    gsap.fromTo(card,
      { opacity: 0, y: 30 },
      {
        opacity: 1,
        y: 0,
        duration: 0.6,
        delay: i * 0.08,           /* stagger each card slightly */
        ease: 'power3.out',
        scrollTrigger: {
          trigger: card,
          start: 'top 90%',
          once: true
        }
      }
    );
  });

  /* ── NBA card entrance (gold accent pages) ─────────────────────────────────── */
  gsap.utils.toArray('.nba-card').forEach((card, i) => {
    if (!card.classList.contains('glow-card')) {
      gsap.fromTo(card,
        { opacity: 0, y: 24 },
        {
          opacity: 1,
          y: 0,
          duration: 0.55,
          delay: i * 0.07,
          ease: 'power3.out',
          scrollTrigger: {
            trigger: card,
            start: 'top 92%',
            once: true
          }
        }
      );
    }
  });

  /* ── Feature card entrance (home page grid) ─────────────────────────────────── */
  gsap.utils.toArray('.feature-card').forEach((card, i) => {
    gsap.fromTo(card,
      { opacity: 0, scale: 0.96, y: 20 },
      {
        opacity: 1,
        scale: 1,
        y: 0,
        duration: 0.5,
        delay: i * 0.06,
        ease: 'back.out(1.4)',
        scrollTrigger: {
          trigger: card,
          start: 'top 92%',
          once: true
        }
      }
    );
  });

}

/* ── Animated stat counters ────────────────────────────────────────────────── */
function animateCounter(el) {
  const target = parseFloat(el.dataset.target);
  if (isNaN(target)) return;
  const isDecimal = target % 1 !== 0;
  let current = 0;
  const increment = target / 60;

  const timer = setInterval(() => {
    current += increment;
    if (current >= target) {
      current = target;
      clearInterval(timer);
    }
    el.textContent = isDecimal ? current.toFixed(1) : Math.floor(current);
  }, 16);
}

const counterObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      animateCounter(entry.target);
      counterObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.2 });

document.querySelectorAll('.stat-number[data-target]').forEach(el => {
  counterObserver.observe(el);
});

/* ── Probability bars: animate fill on scroll into view ─────────────────────── */
const barObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const fill = entry.target.querySelector('.prob-bar-fill');
      if (fill) {
        setTimeout(() => {
          fill.style.width = (fill.dataset.width || '0') + '%';
        }, 200);
      }
      barObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.prob-bar').forEach(bar => {
  barObserver.observe(bar);
});

/* Also animate existing win-fill bars (prediction page) */
const winFillObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.querySelectorAll('.win-fill, .fpred-prob-fill').forEach(fill => {
        const w = fill.style.width;
        fill.style.width = '0%';
        requestAnimationFrame(() => {
          setTimeout(() => { fill.style.width = w; }, 150);
        });
      });
      winFillObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.win-probs, .fpred-probs').forEach(el => {
  winFillObserver.observe(el);
});

/* ── Shimmer → real content swap ─────────────────────────────────────────────── */
document.querySelectorAll('.shimmer-wrap').forEach(wrap => {
  const content = wrap.querySelector('.shimmer-content');
  if (content && content.innerHTML.trim() !== '') {
    wrap.classList.remove('shimmer');
  }
});

/* ── Mobile nav toggle ───────────────────────────────────────────────────────── */
const navToggle = document.getElementById('navToggle');
const navLinks  = document.querySelector('.nav-links');
if (navToggle && navLinks) {
  navToggle.addEventListener('click', () => {
    navLinks.classList.toggle('open');
  });
}

/* ── Tab buttons: add tab-active class to active tab ────────────────────────── */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.closest('.tab-bar')
       ?.querySelectorAll('.tab-btn')
       .forEach(b => b.classList.remove('tab-active'));
    btn.classList.add('tab-active');
  });
  /* Mark initial active tab */
  if (btn.classList.contains('active')) {
    btn.classList.add('tab-active');
  }
});

/* NBA tabs */
document.querySelectorAll('.nba-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.closest('.nba-tabs')
       ?.querySelectorAll('.nba-tab')
       .forEach(b => b.classList.remove('tab-active'));
    btn.classList.add('tab-active');
  });
  if (btn.classList.contains('active')) {
    btn.classList.add('tab-active');
  }
});

/* Chat bubble */
const chatToggle = document.getElementById('chat-toggle');
const chatWindow = document.getElementById('chat-window');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');
const chatClear = document.getElementById('chat-clear');

function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

function csrfHeaders(extra = {}) {
  const token = getCsrfToken();
  return token ? { ...extra, 'X-CSRF-Token': token } : extra;
}

document.querySelectorAll('form').forEach(form => {
  const method = (form.getAttribute('method') || 'GET').toUpperCase();
  if (method !== 'POST') return;
  if (form.querySelector('input[name="csrf_token"]')) return;
  const token = getCsrfToken();
  if (!token) return;
  const input = document.createElement('input');
  input.type = 'hidden';
  input.name = 'csrf_token';
  input.value = token;
  form.appendChild(input);
});

function appendChatMessage(role, text) {
  if (!chatMessages || !text) return;
  const row = document.createElement('div');
  row.className = `chat-message ${role}`;
  row.textContent = text;
  chatMessages.appendChild(row);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

if (chatToggle && chatWindow) {
  chatToggle.addEventListener('click', () => {
    const open = chatWindow.classList.toggle('open');
    chatWindow.setAttribute('aria-hidden', open ? 'false' : 'true');
    chatToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open && chatInput) chatInput.focus();
  });
}

if (chatForm && chatInput) {
  chatForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const message = chatInput.value.trim();
    if (!message) return;
    appendChatMessage('user', message);
    chatInput.value = '';
    try {
      const response = await fetch('/chat', {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' }),
        body: new URLSearchParams({ message, csrf_token: getCsrfToken() }).toString()
      });
      const data = await response.json();
      appendChatMessage('assistant', data.reply || data.error || 'No reply available.');
    } catch (error) {
      appendChatMessage('assistant', 'Chat is temporarily unavailable.');
    }
  });
}

if (chatClear) {
  chatClear.addEventListener('click', async () => {
    try {
      await fetch('/chat/clear', {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' }),
        body: new URLSearchParams({ csrf_token: getCsrfToken() }).toString()
      });
    } catch (error) {
      console.error(error);
    }
    if (chatMessages) {
      chatMessages.innerHTML = '<div class="chat-message assistant">Ask about predictions, props, injuries, or where to find a page.</div>';
    }
  });
}
