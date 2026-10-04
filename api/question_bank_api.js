/**
 * Browser-side client for the MathCyclus localhost draft API.
 *
 * This client can be imported by a local helper page, browser extension, or
 * pasted into a module-enabled GPT companion page. It cannot approve or
 * commit questions; those actions remain in the human review UI.
 */

export class MathCyclusApi {
  constructor({ baseUrl = "http://127.0.0.1:8765", token = "" } = {}) {
    this.baseUrl = String(baseUrl).replace(/\/$/, "");
    this.token = String(token || "");
  }

  async request(path, { method = "GET", body, params } = {}) {
    const url = new URL(`${this.baseUrl}${path}`);
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          url.searchParams.set(key, String(value));
        }
      });
    }
    const headers = { Accept: "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload.error || `HTTP ${response.status}`;
      throw new Error(message);
    }
    return payload;
  }

  health() {
    return this.request("/health");
  }

  createDrafts(items, options = {}) {
    return this.request("/api/v1/drafts", {
      method: "POST",
      body: { ...options, items },
    });
  }

  createDraft(item, options = {}) {
    return this.createDrafts([item], options);
  }

  getDraft(draftId) {
    return this.request(`/api/v1/drafts/${encodeURIComponent(draftId)}`);
  }

  updateDraft(draftId, updates, operator = "browser_helper") {
    return this.request(`/api/v1/drafts/${encodeURIComponent(draftId)}`, {
      method: "PATCH",
      body: { updates, operator },
    });
  }

  validateDraft(draftId) {
    return this.request(`/api/v1/drafts/${encodeURIComponent(draftId)}/validate`, {
      method: "POST",
    });
  }

  reviewEvents(draftId, limit = 100) {
    return this.request(`/api/v1/drafts/${encodeURIComponent(draftId)}/review-events`, {
      params: { limit },
    });
  }

  listDrafts({ batchId = "", reviewStatus = "", limit = 50, offset = 0 } = {}) {
    return this.request("/api/v1/drafts", {
      params: { batch_id: batchId, review_status: reviewStatus, limit, offset },
    });
  }

  listBatches(limit = 20) {
    return this.request("/api/v1/batches", { params: { limit } });
  }

  getBatch(batchId) {
    return this.request(`/api/v1/batches/${encodeURIComponent(batchId)}`);
  }

  validateBatch(batchId) {
    return this.request(`/api/v1/batches/${encodeURIComponent(batchId)}/validate`, {
      method: "POST",
    });
  }

  searchQuestions(filters = {}) {
    return this.request("/api/v1/questions/search", { params: filters });
  }

  findSimilarQuestions({ stem_tex, choices = [], question_type_id = null, minimum_score = 0.4, max_results = 20 } = {}) {
    return this.request("/api/v1/questions/similarity", {
      method: "POST",
      body: { stem_tex, choices, question_type_id, minimum_score, max_results },
    });
  }

  matchPaper({ year = "", paper_series = "G", track = "", paper_name = "", limit = 5, similarity_threshold = 0.55 } = {}) {
    return this.request("/api/v1/papers/match", {
      method: "POST",
      body: { year, paper_series, track, paper_name, limit, similarity_threshold },
    });
  }

  getQuestion(questionId) {
    return this.request(`/api/v1/questions/${encodeURIComponent(questionId)}`);
  }
}
