/* i18n: loads locale JSON, provides t(), and rewrites the DOM. */
(function () {
  const DEFAULT_LANG = "zh-CN";
  const SUPPORTED = ["zh-CN", "en-US"];

  const I18N = {
    lang: DEFAULT_LANG,
    dict: {},

    t(key, params) {
      let v = key.split(".").reduce((o, k) => (o && o[k] != null ? o[k] : undefined), this.dict);
      if (v == null) return key;
      if (typeof v === "string" && params) {
        Object.keys(params).forEach((k) => {
          v = v.replace("{" + k + "}", params[k]);
        });
      }
      return v;
    },

    async load(lang) {
      if (!SUPPORTED.includes(lang)) lang = DEFAULT_LANG;
      try {
        const resp = await fetch(`/locales/${lang}.json`, { cache: "no-store" });
        if (!resp.ok) throw new Error("bad locale");
        this.dict = await resp.json();
        this.lang = lang;
      } catch (e) {
        this.lang = DEFAULT_LANG;
        const resp = await fetch(`/locales/${DEFAULT_LANG}.json`);
        this.dict = await resp.json();
      }
      document.documentElement.lang = this.lang;
      this.apply();
      this.updateToggle();
    },

    apply() {
      document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.textContent = this.t(el.getAttribute("data-i18n"));
      });
      document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        el.placeholder = this.t(el.getAttribute("data-i18n-placeholder"));
      });
      document.title = "Ollama Monitor";
      const note = document.getElementById("footerNote");
      if (note) note.textContent = this.t("common.footerNote");
    },

    updateToggle() {
      const btn = document.getElementById("langToggle");
      if (!btn) return;
      btn.textContent = this.lang === "zh-CN" ? "English" : "中文";
    },

    async toggle() {
      const next = this.lang === "zh-CN" ? "en-US" : "zh-CN";
      await this.load(next);
      try {
        await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ language: this.lang }),
        });
      } catch (e) { /* non-fatal */ }
      try { localStorage.setItem("om-language", this.lang); } catch (e) {}
      if (window.refreshAll) window.refreshAll();
    },
  };

  window.I18N = I18N;
})();
