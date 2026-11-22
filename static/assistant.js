const assistantContext = document.querySelector("#assistant-context");
const assistantForm = document.querySelector("#assistant-form");
const assistantMessages = document.querySelector("#assistant-messages");

if (assistantContext && assistantForm && assistantMessages) {
  const byId = (id) => document.getElementById(id);
  const notice = byId("assistant-notice");
  const levelSelect = byId("assistant-level");
  const topicInput = byId("assistant-topic");
  const resourceInput = byId("assistant-files");
  const uploadButton = byId("upload-resources");
  const questionInput = byId("assistant-question");
  const sendButton = assistantForm.querySelector("button[type='submit']");
  const sessionStorageKey = "classe-claire-resource-session";
  const indexedStorageKey = "classe-claire-resource-indexed";
  const namesStorageKey = "classe-claire-resource-names";
  const conversationStorageKey = "classe-claire-conversation-id";
  const maximumUploadBytes = 4 * 1024 * 1024;
  const promptTemplates = {
    sequence: "Prépare une séquence pédagogique adaptée au niveau {level} en {subject} sur le thème « {topic} ». Propose des objectifs, des prérequis, des séances progressives, les activités de l’enseignant et des élèves, les supports et une évaluation.",
    differentiation: "Sur le thème « {topic} » en {subject} au niveau {level}, propose trois activités pour le même objectif : une pour les élèves avancés, une pour les élèves intermédiaires et une pour les élèves en difficulté. Adapte les aides sans réduire l’objectif. Sépare les consignes élèves des corrigés et ajoute critères de réussite et vérification rapide.",
    exercises: "Crée des exercices progressifs avec corrigés expliqués sur « {topic} » en {subject} au niveau {level}. Vérifie la justesse des réponses et adapte les consignes à l’âge des élèves.",
    evaluation: "Prépare une évaluation formative sur « {topic} » en {subject} pour le niveau {level}, avec consignes, barème, critères de réussite et corrigé séparé.",
    visual: "Rédige un prompt pour créer un support visuel pédagogique sur « {topic} » en {subject} au niveau {level}. Ne génère pas l’image. Précise les notions, la composition, la langue et les exigences de lisibilité et d’exactitude.",
  };

  let selectedLevel = "";
  let selectedSubject = "";
  let resourcesIndexed = sessionStorage.getItem(indexedStorageKey) === "true";
  let conversation = [];
  let conversationId = localStorage.getItem(conversationStorageKey) || "";
  let restorePromise = Promise.resolve(false);

  function createSessionId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  let resourceSession = sessionStorage.getItem(sessionStorageKey) || createSessionId();
  sessionStorage.setItem(sessionStorageKey, resourceSession);

  function showNotice(message) {
    notice.textContent = message;
    notice.hidden = false;
  }

  function hideNotice() {
    notice.hidden = true;
    notice.textContent = "";
  }

  function showStep(stepId) {
    document.querySelectorAll(".wizard-step").forEach((step) => {
      step.hidden = step.id !== stepId;
    });
  }

  function updateProgress(currentStep, complete = false) {
    const progress = byId("assistant-progress");
    if (!progress) return;
    progress.hidden = complete;
    const steps = [...progress.querySelectorAll("[data-progress-step]")];
    const activeIndex = steps.findIndex((step) => step.dataset.progressStep === currentStep);
    steps.forEach((step, index) => {
      step.classList.toggle("is-current", index === activeIndex);
      step.classList.toggle("is-complete", activeIndex >= 0 && index < activeIndex);
      if (index === activeIndex) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    });
  }

  function updateChatContextLabel() {
    const topic = topicInput.value.trim();
    const resourceText = resourcesIndexed ? " · ressources chargées" : " · sans document";
    byId("chat-context-label").textContent = `${selectedLevel} · ${selectedSubject}${topic ? ` · ${topic}` : ""}${resourceText}`;
  }

  function updateSaveStatus(expiresAt) {
    const expiry = expiresAt ? new Date(expiresAt) : null;
    byId("conversation-save-status").textContent = expiry && !Number.isNaN(expiry.getTime())
      ? `Sauvegardée jusqu’au ${expiry.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}`
      : "Sauvegarde Redis · conservation glissante de 7 jours";
  }

  async function errorFromResponse(response, fallback) {
    let body = {};
    try { body = await response.json(); } catch { }
    const detail = body.detail;
    const error = new Error(typeof detail === "string" ? detail : detail?.message || fallback);
    error.code = detail?.code;
    error.status = response.status;
    return error;
  }


  function renderResourceNames(names) {
    const list = byId("resource-file-list");
    list.replaceChildren();
    names.forEach((name) => {
      const item = document.createElement("li");
      item.textContent = name;
      list.append(item);
    });
    byId("clear-resources").hidden = names.length === 0;
  }

  function resetResourceState() {
    resourcesIndexed = false;
    sessionStorage.setItem(indexedStorageKey, "false");
    sessionStorage.removeItem(namesStorageKey);
    resourceSession = createSessionId();
    sessionStorage.setItem(sessionStorageKey, resourceSession);
    renderResourceNames([]);
    resourceInput.value = "";
    uploadButton.disabled = true;
  }

  async function clearResourceSession() {
    if (resourcesIndexed) {
      const response = await fetch(`/api/resources/${encodeURIComponent(resourceSession)}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Les ressources n’ont pas pu être supprimées de Pinecone.");
    }
    resetResourceState();
  }

  function applyPreset(key) {
    if (key === "custom") {
      byId("assistant-prompt").value = "";
      byId("assistant-prompt").focus();
      return;
    }
    const template = promptTemplates[key];
    if (!template) return;
    byId("assistant-prompt").value = template
      .replaceAll("{level}", selectedLevel)
      .replaceAll("{subject}", selectedSubject)
      .replaceAll("{topic}", topicInput.value.trim() || "à préciser");
  }

  async function selectLevel() {
    const nextLevel = levelSelect.value;
    if (!nextLevel) return;
    if (resourcesIndexed) {
      try {
        await clearResourceSession();
      } catch (error) {
        showNotice(error.message);
        levelSelect.value = selectedLevel;
        return;
      }
    } else {
      resetResourceState();
    }
    selectedLevel = nextLevel;
    selectedSubject = "";
    document.querySelectorAll(".subject-choice").forEach((button) => {
      button.classList.remove("is-selected");
      button.setAttribute("aria-pressed", "false");
    });
    byId("wizard-subject").hidden = false;
    byId("wizard-resources").hidden = true;
    byId("wizard-prompt").hidden = true;
    byId("assistant-chat").hidden = true;
    updateProgress("wizard-subject");
    hideNotice();
  }

  document.querySelectorAll(".subject-choice").forEach((button) => {
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", async () => {
      const nextSubject = button.dataset.subject;
      if (resourcesIndexed) {
        try {
          await clearResourceSession();
        } catch (error) {
          showNotice(error.message);
          return;
        }
      } else {
        resetResourceState();
      }
      selectedSubject = nextSubject;
      document.querySelectorAll(".subject-choice").forEach((choice) => {
        const isSelected = choice === button;
        choice.classList.toggle("is-selected", isSelected);
        choice.setAttribute("aria-pressed", String(isSelected));
      });
      byId("wizard-resources").hidden = false;
      byId("wizard-prompt").hidden = true;
      byId("assistant-chat").hidden = true;
      updateProgress("wizard-resources");
      hideNotice();
    });
  });

  levelSelect.addEventListener("change", selectLevel);
  resourceInput.addEventListener("change", () => {
    const files = [...resourceInput.files];
    const totalSize = files.reduce((sum, file) => sum + file.size, 0);
    const allowed = files.every((file) => /\.(pdf|docx|txt)$/i.test(file.name));
    if (totalSize > maximumUploadBytes) {
      resourceInput.value = "";
      renderResourceNames([]);
      uploadButton.disabled = true;
      showNotice("La taille totale des fichiers ne doit pas dépasser 4 Mo.");
      return;
    }
    if (!allowed) {
      resourceInput.value = "";
      renderResourceNames([]);
      uploadButton.disabled = true;
      showNotice("Formats acceptés : PDF, DOCX et TXT.");
      return;
    }
    hideNotice();
    renderResourceNames(files.map((file) => `${file.name} · ${(file.size / 1024).toFixed(0)} Ko`));
    uploadButton.disabled = files.length === 0;
  });

  uploadButton.addEventListener("click", async () => {
    const files = [...resourceInput.files];
    if (!files.length || !selectedLevel || !selectedSubject) return;
    const data = new FormData();
    data.append("resource_session", resourceSession);
    data.append("level", selectedLevel);
    data.append("subject", selectedSubject);
    files.forEach((file) => data.append("files", file));
    uploadButton.disabled = true;
    uploadButton.textContent = "Extraction et indexation…";
    hideNotice();

    try {
      const response = await fetch("/api/resources", { method: "POST", body: data });
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(typeof result.detail === "string" ? result.detail : result.detail?.message || "L’indexation des ressources a échoué.");
        error.code = result.detail?.code;
        throw error;
      }
      resourcesIndexed = true;
      sessionStorage.setItem(indexedStorageKey, "true");
      const names = result.resources.map((resource) => `${resource.filename} · ${resource.chunks_indexed} fragments indexés`);
      sessionStorage.setItem(namesStorageKey, JSON.stringify(names));
      renderResourceNames(names);
      byId("skip-resources").hidden = resourcesIndexed;
      byId("wizard-prompt").hidden = false;
      updateProgress("wizard-prompt");
      byId("wizard-prompt").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      showNotice(error.code === "rag_not_configured"
        ? "Le service d’indexation n’est pas configuré. Ajoutez les clés OpenAI et Pinecone dans les variables d’environnement. Vous pouvez continuer sans document."
        : error.message || "Connexion impossible. Réessayez dans un instant.");
      uploadButton.disabled = false;
    } finally {
      uploadButton.innerHTML = 'Charger et continuer <span aria-hidden="true">→</span>';
    }
  });

  byId("skip-resources").addEventListener("click", () => {
    resourcesIndexed = false;
    byId("wizard-prompt").hidden = false;
    updateProgress("wizard-prompt");
    byId("wizard-prompt").scrollIntoView({ behavior: "smooth", block: "start" });
    hideNotice();
  });

  byId("clear-resources").addEventListener("click", async () => {
    try {
      await clearResourceSession();
      byId("wizard-prompt").hidden = true;
      showNotice("Les ressources de cette session ont été supprimées.");
    } catch (error) {
      showNotice(error.message);
    }
  });

  byId("prompt-choice").addEventListener("change", (event) => applyPreset(event.target.value));
  topicInput.addEventListener("input", () => {
    const choice = byId("prompt-choice").value;
    if (choice && choice !== "custom") applyPreset(choice);
  });

  byId("start-chat").addEventListener("click", async () => {
    await restorePromise;
    const prompt = byId("assistant-prompt").value.trim();
    if (!selectedLevel || !selectedSubject || !prompt) {
      showNotice("Choisissez un modèle ou rédigez votre prompt avant de continuer.");
      return;
    }
    hideNotice();
    const startButton = byId("start-chat");
    startButton.disabled = true;
    startButton.textContent = "Création de la conversation…";
    try {
      const response = await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          level: selectedLevel,
          subject: selectedSubject,
          topic: topicInput.value.trim(),
          pedagogical_prompt: prompt,
          resource_session: resourcesIndexed ? resourceSession : null,
        }),
      });
      if (!response.ok) {
        throw await errorFromResponse(response, "La conversation n’a pas pu être sauvegardée.");
      }
      const record = await response.json();
      conversationId = record.id;
      localStorage.setItem(conversationStorageKey, conversationId);
      conversation = [];
      assistantMessages.replaceChildren();
      addMessage("assistant", "Bonjour ! Votre conversation est sauvegardée. Quelle activité souhaitez-vous préparer ?", [], null);
      updateChatContextLabel();
      updateSaveStatus(record.expires_at);
      byId("assistant-chat").hidden = false;
      updateProgress("wizard-prompt", true);
      assistantContext.hidden = true;
      byId("assistant-chat").scrollIntoView({ behavior: "smooth", block: "start" });
      questionInput.focus();
    } catch (error) {
      showNotice(error.code === "redis_not_configured"
        ? "La sauvegarde Redis n’est pas configurée. Ajoutez les identifiants Upstash pour démarrer une conversation persistante."
        : error.message || "La conversation n’a pas pu être créée.");
    } finally {
      startButton.disabled = false;
      startButton.innerHTML = 'Continuer vers la conversation <span aria-hidden="true">→</span>';
    }
  });

  byId("back-to-resources").addEventListener("click", () => {
    byId("wizard-resources").hidden = false;
    byId("wizard-prompt").hidden = true;
    updateProgress("wizard-resources");
    byId("assistant-prompt").value = "";
    byId("prompt-choice").value = "";
  });

  byId("clear-conversation").addEventListener("click", async () => {
    const clearButton = byId("clear-conversation");
    clearButton.disabled = true;
    try {
      if (conversationId) {
        const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
        if (!response.ok) throw await errorFromResponse(response, "La conversation n’a pas pu être supprimée.");
      }
      if (resourcesIndexed && resourceSession) {
        const response = await fetch(`/api/resources/${encodeURIComponent(resourceSession)}`, { method: "DELETE" });
        if (!response.ok) throw await errorFromResponse(response, "Les ressources associées n’ont pas pu être supprimées.");
      }
      localStorage.removeItem(conversationStorageKey);
      sessionStorage.removeItem(sessionStorageKey);
      sessionStorage.removeItem(indexedStorageKey);
      sessionStorage.removeItem(namesStorageKey);
      window.location.reload();
    } catch (error) {
      showNotice(error.message || "La conversation n’a pas pu être supprimée.");
      clearButton.disabled = false;
    }
  });

  function addMessage(role, content, sources = [], evidenceStatus = "general") {
    const article = document.createElement("article");
    article.className = `chat-message ${role === "assistant" ? "assistant-message" : "user-message"}`;
    if (role === "assistant") {
      const mark = document.createElement("span");
      mark.className = "message-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "c.";
      article.append(mark);
    }
    const contentBlock = document.createElement("div");
    contentBlock.className = "message-content";
    const author = document.createElement("span");
    author.className = "message-author";
    author.textContent = role === "assistant" ? "CLASSE CLAIRE" : "VOUS";
    const text = document.createElement("p");
    text.dir = "auto";
    text.textContent = content;
    contentBlock.append(author, text);

    if (role === "assistant" && evidenceStatus) {
      const evidence = document.createElement("span");
      evidence.className = `evidence-label${evidenceStatus === "documented" ? " is-documented" : ""}`;
      evidence.textContent = evidenceStatus === "documented"
        ? "Réponse appuyée par des ressources"
        : "Proposition générale, non vérifiée dans les ressources";
      contentBlock.append(evidence);
      if (sources.length) {
        const sourceList = document.createElement("div");
        sourceList.className = "source-list";
        const sourceHeading = document.createElement("span");
        sourceHeading.className = "source-heading";
        sourceHeading.textContent = "RÉFÉRENCES RETROUVÉES";
        sourceList.append(sourceHeading);
        sources.forEach((source) => {
          const sourceLine = document.createElement("p");
          sourceLine.textContent = `${source.id} · ${source.title}${source.page ? ` · p. ${source.page}` : ""}${source.chapter ? ` · ${source.chapter}` : ""}`;
          sourceList.append(sourceLine);
        });
        contentBlock.append(sourceList);
      }
    }
    article.append(contentBlock);
    assistantMessages.append(article);
    assistantMessages.scrollTop = assistantMessages.scrollHeight;
  }

  function showTypingIndicator() {
    const article = document.createElement("article");
    article.className = "chat-message assistant-message is-typing";
    article.setAttribute("aria-label", "Classe Claire prépare une réponse");
    const mark = document.createElement("span");
    mark.className = "message-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = "c.";
    const dots = document.createElement("div");
    dots.className = "typing-dots";
    dots.innerHTML = "<i></i><i></i><i></i>";
    article.append(mark, dots);
    assistantMessages.append(article);
    assistantMessages.scrollTop = assistantMessages.scrollHeight;
    return article;
  }

  assistantForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = questionInput.value.trim();
    if (!question) return;
    if (!conversationId) {
      showNotice("Créez une conversation pour activer sa sauvegarde.");
      return;
    }
    hideNotice();
    conversation.push({ role: "user", content: question });
    addMessage("user", question);
    questionInput.value = "";
    sendButton.disabled = true;
    sendButton.textContent = "Recherche…";
    const typingIndicator = showTypingIndicator();
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, message: question }),
      });
      if (!response.ok) {
        throw await errorFromResponse(response, "Une erreur est survenue. Réessayez dans un instant.");
      }
      const result = await response.json();
      conversation.push({ role: "assistant", content: result.answer });
      addMessage("assistant", result.answer, result.sources, result.evidence_status);
      updateSaveStatus(result.expires_at);
    } catch (error) {
      showNotice(error.code === "rag_not_configured"
        ? "Le service documentaire n’est pas configuré. Ajoutez les clés OpenAI et Pinecone côté serveur."
        : error.code === "conversation_expired"
          ? "Cette conversation a expiré. Vous pouvez en créer une nouvelle."
        : error.message || "Connexion impossible. Vérifiez votre réseau puis réessayez.");
      assistantMessages.scrollTop = assistantMessages.scrollHeight;
    } finally {
      typingIndicator.remove();
      sendButton.disabled = false;
      sendButton.innerHTML = 'Envoyer <span aria-hidden="true">→</span>';
      questionInput.focus();
    }
  });

  renderResourceNames(JSON.parse(sessionStorage.getItem(namesStorageKey) || "[]"));
  updateProgress("wizard-level");
  if (levelSelect.value) {
    selectLevel().then(() => {
      const initialSubject = assistantContext.dataset.initialSubject;
      const matchingSubject = [...document.querySelectorAll(".subject-choice")]
        .find((button) => button.dataset.subject === initialSubject);
      if (matchingSubject) matchingSubject.click();
    });
  }

  async function restoreSavedConversation() {
    if (!conversationId) return false;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`);
      if (response.status === 404) {
        localStorage.removeItem(conversationStorageKey);
        if (sessionStorage.getItem(indexedStorageKey) === "true") {
          const oldResourceSession = sessionStorage.getItem(sessionStorageKey);
          if (oldResourceSession) {
            await fetch(`/api/resources/${encodeURIComponent(oldResourceSession)}`, { method: "DELETE" });
          }
          sessionStorage.removeItem(indexedStorageKey);
          sessionStorage.removeItem(namesStorageKey);
        }
        conversationId = "";
        showNotice("Cette conversation a expiré après sa période de conservation.");
        return false;
      }
      if (!response.ok) throw await errorFromResponse(response, "La conversation sauvegardée n’a pas pu être chargée.");

      const record = await response.json();
      selectedLevel = record.level;
      selectedSubject = record.subject;
      levelSelect.value = selectedLevel;
      topicInput.value = record.topic || "";
      byId("assistant-prompt").value = record.pedagogical_prompt || "";
      resourceSession = record.resource_session || resourceSession;
      resourcesIndexed = Boolean(record.resource_session);
      sessionStorage.setItem(sessionStorageKey, resourceSession);
      sessionStorage.setItem(indexedStorageKey, String(resourcesIndexed));
      byId("wizard-prompt").hidden = false;
      byId("assistant-context").hidden = true;
      byId("assistant-chat").hidden = false;
      updateProgress("wizard-prompt", true);
      byId("wizard-subject").hidden = false;
      byId("wizard-resources").hidden = false;
      document.querySelectorAll(".subject-choice").forEach((button) => {
        const selected = button.dataset.subject === selectedSubject;
        button.classList.toggle("is-selected", selected);
        button.setAttribute("aria-pressed", String(selected));
      });
      updateChatContextLabel();
      updateSaveStatus(record.expires_at);
      conversation = record.messages.map(({ role, content }) => ({ role, content }));
      assistantMessages.replaceChildren();
      record.messages.forEach((turn) => {
        addMessage(turn.role, turn.content, turn.sources || [], turn.evidence_status || "general");
      });
      showNotice("Votre conversation sauvegardée a été reprise.");
      return true;
    } catch (error) {
      if (error.status === 503) {
        showNotice(error.code === "redis_not_configured"
          ? "Ajoutez les identifiants Upstash Redis pour retrouver les conversations sauvegardées."
          : error.message);
      } else {
        showNotice(error.message || "La conversation sauvegardée n’a pas pu être chargée.");
      }
      return false;
    }
  }

  restorePromise = restoreSavedConversation();
}
