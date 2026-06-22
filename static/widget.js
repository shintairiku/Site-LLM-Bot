(function () {
  const script = document.currentScript;
  if (!script) {
    return;
  }

  // 埋め込み script タグの data 属性を起点に、ウィジェット表示に必要な設定値を初期化する。
  // 見た目は共通 CSS と tenant 別 CSS で管理し、顧客側の data 属性では制御しない。
  const baseUrl = new URL("./", script.src || window.location.href);
  const productionApiBase = "https://site-llm-bot-742231208085.asia-northeast1.run.app";
  const developmentApiBase = "https://site-llm-bot-dev-742231208085.asia-northeast1.run.app";
  const cssUrl = new URL("widget.css", baseUrl).toString();
  const tenantCssBaseUrl = new URL("tenants/", baseUrl).toString();
  const apiBase = resolveApiBase(
    script.dataset.apiBase
  );
  let tenantId = script.dataset.tenantId || "sample-shintairiku";
  let tenantName = script.dataset.tenantName || "サンプル工務店";
  let publicToken = script.dataset.publicToken || "";
  const visitorId = resolveVisitorId();
  let sessionId = null;
  const suggestions = [
    "施工エリアを教えてください",
    "相談の流れを知りたいです",
    "リフォームも対応していますか？",
  ];

  ensureCss(cssUrl);
  ensureTenantCss(tenantId);

  // ランチャーボタンと本体パネルを先に構築し、以降の各関数は
  // messagesEl / suggestionsEl / statusEl / textarea を共有してUI更新を行う。
  const launcher = document.createElement("button");
  launcher.className = "site-llm-bot-launcher";
  launcher.type = "button";
  launcher.textContent = "AI相談窓口";

  const panel = document.createElement("section");
  panel.className = "site-llm-bot-panel";
  panel.innerHTML = `
    <div class="site-llm-bot-header">
      <h2 class="site-llm-bot-title">${escapeHtml(tenantName)} AI相談窓口</h2>
      <p>住まいに関するご質問を受け付けています。お気軽にご相談ください。</p>
      <button class="site-llm-bot-close" type="button" aria-label="閉じる">×</button>
    </div>
    <div class="site-llm-bot-messages"></div>
    <div class="site-llm-bot-suggestions"></div>
    <div class="site-llm-bot-status">待機中</div>
    <div class="site-llm-bot-feedback">
      <p class="site-llm-bot-feedback-label">問題は解決しましたか？</p>
      <div class="site-llm-bot-feedback-buttons">
        <button type="button" data-resolved="true">✓ 解決した</button>
        <button type="button" data-resolved="false">✗ 未解決</button>
      </div>
    </div>
    <form class="site-llm-bot-form">
      <textarea placeholder="住まいに関するご質問を入力してください"></textarea>
      <button type="submit">送信</button>
    </form>
  `;

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  const messagesEl = panel.querySelector(".site-llm-bot-messages");
  const suggestionsEl = panel.querySelector(".site-llm-bot-suggestions");
  const statusEl = panel.querySelector(".site-llm-bot-status");
  const closeButton = panel.querySelector(".site-llm-bot-close");
  const feedbackEl = panel.querySelector(".site-llm-bot-feedback");
  const feedbackButtonsEl = feedbackEl.querySelector(".site-llm-bot-feedback-buttons");
  const form = panel.querySelector(".site-llm-bot-form");
  const textarea = form.querySelector("textarea");
  const submitButton = form.querySelector("button");
  const titleEl = panel.querySelector(".site-llm-bot-title");
  let feedbackSubmitted = false;

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

  feedbackButtonsEl.querySelectorAll("button").forEach(function (button) {
    button.addEventListener("click", function () {
      if (feedbackSubmitted) {
        return;
      }
      feedbackSubmitted = true;
      const resolved = button.dataset.resolved === "true";
      feedbackButtonsEl.innerHTML = '<span class="site-llm-bot-feedback-thanks">フィードバックありがとうございます</span>';
      recordSessionFeedback(resolved);
    });
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
      ensureTenantCss(tenantId);
    }
    if (detail.tenantName) {
      tenantName = detail.tenantName;
      titleEl.textContent = `${tenantName} AI相談窓口`;
    }
    if (detail.publicToken) {
      publicToken = detail.publicToken;
    }
    sessionId = null;
    setStatus(statusEl, `${tenantName}に切り替えました`, false);
  });

  // 送信処理の中心。入力値検証、ユーザー発話の描画、状態表示更新のあと、
  // 検証済みのJSON応答を受信し、失敗時のみ createMockReply にフォールバックする。
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
      const result = await requestChatMessage(text);
      sessionId = result.session_id || sessionId;
      addMessage(messagesEl, "bot", result.answer || "回答を生成できませんでした。");
      setStatus(
        statusEl,
        "回答を表示しました",
        false
      );
      feedbackEl.classList.add("is-visible");
    } catch (error) {
      addMessage(messagesEl, "bot", createMockReply(text));
      setStatus(statusEl, "ただいま詳しい回答を取得できないため、参考情報を表示しています", false);
      feedbackEl.classList.add("is-visible");
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

  // チャット応答をJSONで受信する。
  async function requestChatMessage(text) {
    const response = await window.fetch(`${apiBase}/v1/chat/message`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-Id": tenantId,
        "X-Widget-Token": publicToken,
      },
      body: JSON.stringify({
        session_id: sessionId,
        message: text,
        metadata: {
          page_url: window.location.href,
          visitor_id: visitorId,
        },
      }),
    });
    if (!response.ok) {
      throw new Error(`chat message request failed: ${response.status}`);
    }

    return response.json();
  }

  function recordSessionFeedback(resolved) {
    requestSessionFeedback(resolved).catch(function () {
      // フィードバック計測の失敗でユーザー操作を妨げない。
    });
  }

  async function requestSessionFeedback(resolved) {
    const response = await window.fetch(`${apiBase}/v1/analytics/session-feedback`, {
      method: "POST",
      keepalive: true,
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-Id": tenantId,
        "X-Widget-Token": publicToken,
      },
      body: JSON.stringify({
        resolved: resolved,
        metadata: {
          page_url: window.location.href,
          visitor_id: visitorId,
          session_id: sessionId,
        },
      }),
    });
    if (!response.ok) {
      throw new Error(`session feedback request failed: ${response.status}`);
    }
  }

  function recordRelatedLinkClick(linkUrl) {
    requestRelatedLinkClick(linkUrl).catch(function () {
      // クリック計測の失敗でユーザーの遷移を妨げない。
    });
  }

  async function requestRelatedLinkClick(linkUrl) {
    const response = await window.fetch(`${apiBase}/v1/analytics/related-link-click`, {
      method: "POST",
      keepalive: true,
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-Id": tenantId,
        "X-Widget-Token": publicToken,
      },
      body: JSON.stringify({
        link_url: linkUrl,
        metadata: {
          page_url: window.location.href,
          visitor_id: visitorId,
          session_id: sessionId,
        },
      }),
    });
    if (!response.ok) {
      throw new Error(`related link click request failed: ${response.status}`);
    }
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
    const node = createEmptyMessage(container, role);
    appendLinkedText(node, text, role);
    container.scrollTop = container.scrollHeight;
    return node;
  }

  // 空のメッセージ節点をコンテナに追加して返す。
  function createEmptyMessage(container, role) {
    const node = document.createElement("div");
    node.className = `site-llm-bot-message ${role}`;
    container.appendChild(node);
    return node;
  }

  // 回答内のURLだけをアンカー化する。本文はtext nodeで追加し、HTMLとして解釈しない。
  function appendLinkedText(node, text, role) {
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
      if (role === "bot" && isRelatedLinkUrl(value, match.index)) {
        anchor.dataset.siteLlmBotRelatedLink = "true";
        anchor.addEventListener("click", function () {
          recordRelatedLinkClick(url);
        });
      }
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

  function isRelatedLinkUrl(text, urlIndex) {
    const markers = ["関連リンク:", "関連リンク："];
    const markerIndexes = markers
      .map(function (marker) {
        return text.indexOf(marker);
      })
      .filter(function (index) {
        return index >= 0;
      });
    if (!markerIndexes.length) {
      return false;
    }
    return urlIndex > Math.min.apply(null, markerIndexes);
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

  function ensureTenantCss(nextTenantId) {
    const href = resolveTenantCssUrl(nextTenantId);
    const existing = document.querySelector('link[data-site-llm-bot-tenant-css="true"]');
    if (!href) {
      if (existing) {
        existing.remove();
      }
      return;
    }
    if (existing) {
      if (existing.href !== href) {
        existing.href = href;
      }
      existing.dataset.siteLlmBotTenantId = nextTenantId;
      return;
    }

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.siteLlmBotTenantCss = "true";
    link.dataset.siteLlmBotTenantId = nextTenantId;
    document.head.appendChild(link);
  }

  function resolveTenantCssUrl(nextTenantId) {
    const value = String(nextTenantId || "").trim();
    if (!/^[a-z0-9][a-z0-9_-]*$/i.test(value)) {
      return null;
    }
    return new URL(`${encodeURIComponent(value)}.css`, tenantCssBaseUrl).toString();
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
