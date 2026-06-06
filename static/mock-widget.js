(function () {
  const script = document.currentScript;
  if (!script) {
    return;
  }

  // 埋め込み script タグの data 属性を起点に、ウィジェット表示に必要な設定値を初期化する。
  // この値は下の render 相当の処理と、テーマ反映、モック応答表示で参照される。
  const baseUrl = new URL("./", script.src || window.location.href);
  const productionApiBase = "https://site-llm-bot-742231208085.asia-northeast1.run.app";
  const developmentApiBase = "https://site-llm-bot-dev-742231208085.asia-northeast1.run.app";
  const cssUrl = new URL("mock-widget.css", baseUrl).toString();
  const apiBase = resolveApiBase(
    script.dataset.apiBase
  );
  let tenantId = script.dataset.tenantId || "sample-shintairiku";
  let tenantName = script.dataset.tenantName || "サンプル工務店";
  let publicToken = script.dataset.publicToken || "";
  let accent = script.dataset.color || "#155e75";
  const visitorId = resolveVisitorId();
  let sessionId = null;
  const suggestions = [
    "施工エリアを教えてください",
    "相談の流れを知りたいです",
    "リフォームも対応していますか？",
  ];

  ensureCss(cssUrl);
  document.documentElement.style.setProperty("--widget-primary", accent);

  // ランチャーボタンと本体パネルを先に構築し、以降の各関数は
  // messagesEl / suggestionsEl / statusEl / textarea を共有してUI更新を行う。
  const launcher = document.createElement("button");
  launcher.className = "mock-chatbot-launcher";
  launcher.type = "button";
  launcher.textContent = "AI相談窓口";

  const panel = document.createElement("section");
  panel.className = "mock-chatbot-panel";
  panel.innerHTML = `
    <div class="mock-chatbot-header">
      <h2 class="mock-chatbot-title">${escapeHtml(tenantName)} AI相談窓口</h2>
      <p>住まいに関するご質問を受け付けています。お気軽にご相談ください。</p>
      <button class="mock-chatbot-close" type="button" aria-label="閉じる">×</button>
    </div>
    <div class="mock-chatbot-messages"></div>
    <div class="mock-chatbot-suggestions"></div>
    <div class="mock-chatbot-status">待機中</div>
    <form class="mock-chatbot-form">
      <textarea placeholder="住まいに関するご質問を入力してください"></textarea>
      <button type="submit">送信</button>
    </form>
  `;

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  const messagesEl = panel.querySelector(".mock-chatbot-messages");
  const suggestionsEl = panel.querySelector(".mock-chatbot-suggestions");
  const statusEl = panel.querySelector(".mock-chatbot-status");
  const closeButton = panel.querySelector(".mock-chatbot-close");
  const form = panel.querySelector(".mock-chatbot-form");
  const textarea = form.querySelector("textarea");
  const submitButton = form.querySelector("button");
  const titleEl = panel.querySelector(".mock-chatbot-title");

  // 初期メッセージは addMessage に集約しておき、
  // 送信時のユーザー発話追加・モック応答追加も同じ導線で処理する。
  addMessage(
    messagesEl,
    "bot",
    "こんにちは。住まいに関するご質問をお受けします。\nまずは施工エリアや相談の流れなど、簡単な内容からお試しください。"
  );

  // 候補質問ボタンは textarea への入力補助のみを担当する。
  // 実送信は form submit に一本化しているため、入力経路が増えても送信処理が分散しない。
  suggestions.forEach(function (question) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = question;
    button.addEventListener("click", function () {
      textarea.value = question;
      textarea.focus();
    });
    suggestionsEl.appendChild(button);
  });

  // 開閉処理はこのクリックイベントだけに閉じ込め、見た目状態は CSS の is-open で管理する。
  launcher.addEventListener("click", function () {
    panel.classList.toggle("is-open");
    statusEl.textContent = panel.classList.contains("is-open")
      ? "チャットを表示中"
      : "待機中";
    if (panel.classList.contains("is-open")) {
      textarea.focus();
    }
  });

  closeButton.addEventListener("click", function () {
    panel.classList.remove("is-open");
    setStatus(statusEl, "待機中", false);
  });

  window.addEventListener("site-llm-bot:tenant-change", function (event) {
    const detail = event.detail || {};
    if (detail.tenantId) {
      tenantId = detail.tenantId;
    }
    if (detail.tenantName) {
      tenantName = detail.tenantName;
      titleEl.textContent = `${tenantName} AI相談窓口`;
    }
    if (detail.publicToken) {
      publicToken = detail.publicToken;
    }
    if (detail.color) {
      accent = detail.color;
      document.documentElement.style.setProperty("--widget-primary", accent);
    }
    sessionId = null;
    setStatus(statusEl, `${tenantName}に切り替えました`, false);
  });

  // 送信処理の中心。入力値検証、ユーザー発話の描画、状態表示更新のあと、
  // まず API へ問い合わせ、失敗時のみ createMockReply にフォールバックする。
  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const text = textarea.value.trim();
    if (!text) {
      return;
    }

    textarea.value = "";
    addMessage(messagesEl, "user", text);
    setBusyState(textarea, submitButton, suggestionsEl, true);
    setStatus(statusEl, "回答を準備しています...", true);

    try {
      const reply = await requestChatAnswer(text);
      sessionId = reply.session_id || sessionId;
      addMessage(messagesEl, "bot", reply.answer);
      setStatus(
        statusEl,
        "回答を表示しました",
        false
      );
    } catch (error) {
      addMessage(messagesEl, "bot", createMockReply(text));
      setStatus(statusEl, "ただいま詳しい回答を取得できないため、参考情報を表示しています", false);
    } finally {
      setBusyState(textarea, submitButton, suggestionsEl, false);
      textarea.focus();
    }
  });

  // Enter だけで送信できるようにし、Shift+Enter は改行に残す。
  textarea.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // 入力文の簡易ルールに応じてモック応答文を返す。
  // 送信イベントからのみ呼ばれる純粋関数にしているため、
  // 将来は API 応答がない場合のフォールバック文言生成にも流用しやすい。
  function createMockReply(text) {
    if (text.includes("施工") || text.includes("エリア")) {
      return "施工エリアに関するご質問ですね。\n対応地域の目安を確認し、担当者からご案内できる内容をお伝えします。";
    }
    if (text.includes("リフォーム")) {
      return "リフォームのご相談にも対応しています。\nご希望の内容や建物の状況をお聞かせください。";
    }
    if (text.includes("相談") || text.includes("流れ")) {
      return "ご相談の流れは、初回相談、ヒアリング、ご提案の順で進みます。\n気になる点からお気軽にご相談ください。";
    }
    return "ありがとうございます。\n内容を確認し、住まいに関するご相談としてご案内します。";
  }

  // FastAPI 側の最小ハンドラを呼び出す関数。
  // UI 側はこの関数から answer/source を受け取り、描画ロジックとは分離している。
  async function requestChatAnswer(text) {
    const response = await window.fetch(`${apiBase}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-Id": script.dataset.tenantId || tenantId,
        "X-Widget-Token": script.dataset.publicToken || publicToken,
      },
      body: JSON.stringify({
        tenant_id: script.dataset.tenantId || tenantId,
        message: text,
        page_url: window.location.href,
        session_id: sessionId,
        visitor_id: visitorId,
      }),
    });
    if (!response.ok) {
      throw new Error("chat api request failed");
    }
    return response.json();
  }

  // 送信中の多重送信を防ぎ、入力部品の状態をまとめて切り替える。
  function setBusyState(textareaEl, submitButtonEl, suggestionsContainer, isBusy) {
    textareaEl.disabled = isBusy;
    submitButtonEl.disabled = isBusy;
    suggestionsContainer.querySelectorAll("button").forEach(function (button) {
      button.disabled = isBusy;
    });
  }

  // ステータス文言と装飾を共通化し、待機中/通信中/完了の表現を揃える。
  function setStatus(statusElement, text, isBusy) {
    statusElement.textContent = text;
    statusElement.classList.toggle("is-busy", isBusy);
  }

  // メッセージ描画の共通関数。
  // 初期メッセージ、ユーザー発話、bot 応答のすべてがここを通ることで、
  // DOM 構造とスクロール制御を一か所で保守できる。
  function addMessage(container, role, text) {
    const node = document.createElement("div");
    node.className = `mock-chatbot-message ${role}`;
    appendLinkedText(node, text);
    container.appendChild(node);
    container.scrollTop = container.scrollHeight;
    return node;
  }

  // 回答内のURLだけをアンカー化する。本文はtext nodeで追加し、HTMLとして解釈しない。
  function appendLinkedText(node, text) {
    const value = String(text);
    const urlPattern = /https?:\/\/[^\s<>"']+/g;
    let lastIndex = 0;
    let match;

    while ((match = urlPattern.exec(value)) !== null) {
      if (match.index > lastIndex) {
        node.appendChild(document.createTextNode(value.slice(lastIndex, match.index)));
      }

      const rawUrl = match[0];
      const url = rawUrl.replace(/[.,)]+$/, "");
      const trailingText = rawUrl.slice(url.length);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.textContent = url;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      node.appendChild(anchor);
      if (trailingText) {
        node.appendChild(document.createTextNode(trailingText));
      }
      lastIndex = match.index + rawUrl.length;
    }

    if (lastIndex < value.length) {
      node.appendChild(document.createTextNode(value.slice(lastIndex)));
    }
  }

  // CSS の重複読み込みを避けつつ、script 設置だけでウィジェットを自己完結させるための関数。
  // ウィジェット本体は見た目をこの関数経由で前提化しているため、初期化のかなり早い段階で実行する。
  function ensureCss(href) {
    if (document.querySelector(`link[href="${href}"]`)) {
      return;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }

  function resolveApiBase(configuredApiBase) {
    if (configuredApiBase && configuredApiBase !== "__WIDGET_API_BASE__") {
      return configuredApiBase.replace(/\/+$/, "");
    }
    if (configuredApiBase === "" && window.location.origin !== "null") {
      return window.location.origin;
    }
    if (
      window.location.origin !== "null" &&
      (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
    ) {
      return window.location.origin;
    }
    if (baseUrl.hostname === new URL(developmentApiBase).hostname) {
      return developmentApiBase;
    }
    return productionApiBase;
  }

  function resolveVisitorId() {
    const storageKey = "site-llm-bot-visitor-id";
    const storage = resolveLocalStorage();
    if (storage) {
      const existing = storage.getItem(storageKey);
      if (existing) {
        return existing;
      }
      const nextId = generateVisitorId();
      storage.setItem(storageKey, nextId);
      return nextId;
    }
    return generateVisitorId();
  }

  function resolveLocalStorage() {
    try {
      return window.localStorage || null;
    } catch (error) {
      return null;
    }
  }

  function generateVisitorId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    const randomValue = Math.random().toString(36).slice(2, 12);
    return `${Date.now().toString(36)}-${randomValue}`;
  }

  // パネルのタイトルに tenantName を埋め込むための最低限のエスケープ関数。
  // innerHTML に外部値を入れる箇所はここを通す前提にして、XSS の混入点を限定する。
  function escapeHtml(text) {
    return String(text)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
})();
