(() => {
  const $ = (selector) => document.querySelector(selector);
  const cardsHost = $("#cards");
  let dashboard;
  let activeView = "today";
  let activeMonth;
  let dashboardRetryAttempt = 0;
  let deckCards = [];
  let deckIndex = 0;
  let dragState = null;
  let deckTimer;

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const moneyNumber = (value, digits = 2) => Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
  const monthName = (month) => new Intl.DateTimeFormat("en", { month: "long" }).format(new Date(2020, month - 1, 1));

  function exposureUrl(item) {
    return item.ticker
      ? `https://finance.yahoo.com/quote/${encodeURIComponent(item.ticker)}/`
      : `https://www.google.com/search?q=${encodeURIComponent(`${item.name} ${item.why || "investment exposure"}`)}`;
  }

  function metricText(metrics) {
    return escapeHtml(metrics?.headline || "Data loading");
  }

  function opportunityTone(label) {
    const text = String(label || "").toUpperCase();
    if (text.startsWith("BUY-SIDE INCOME")) return "income";
    if (text.startsWith("SELL-SIDE")) return "sell";
    if (text.startsWith("BUY-SIDE")) return "buy";
    if (text.startsWith("TWO-SIDED")) return "mixed";
    return "neutral";
  }

  function cardIllustration(card) {
    const scenes = {
      major_averages: '<path d="M38 119h244M54 111V83h28v28m20 0V65h28v46m20 0V48h28v63m20 0V72h28v39m20 0V34h28v77"/><path d="m48 72 47-18 35 9 43-31 37 16 55-25" class="art-line"/><circle cx="265" cy="23" r="6" class="art-dot"/>',
      cash: '<path d="M24 105c5-19 16-27 28-17 8-16 22-13 27 6l9 4-4 12-10-3-3 26h-8l-4-19-13 1-5 18h-8l2-21-12-3z"/><path d="m39 88 5-13 7 12m16-1 3-13 7 18M27 105l-9 5 8 6m2-11-7-7m69 22h184"/><ellipse cx="168" cy="116" rx="61" ry="14"/><path d="M107 97c0-8 27-15 61-15s61 7 61 15v17c0 8-27 15-61 15s-61-7-61-15z"/><ellipse cx="168" cy="97" rx="61" ry="15"/><path d="M122 73c0-7 20-12 46-12s46 5 46 12v14c-12-4-28-6-46-6s-34 2-46 6z"/><circle cx="168" cy="100" r="9"/><path d="M168 91v18m-7-14h11l-1 4h-9l-1 4h11"/>',
      rates: '<path d="M34 121h238M43 119V96m-9 0h18m-14-8 5-15 5 15m8 31V87m-9 0h18m-14-8 5-15 5 15M62 111V57m54 54V79m54 32V46m54 65V67"/><path d="M63 51c34-4 47 27 75 27s42-35 67-35 32 12 54 9" class="art-line"/><circle cx="259" cy="52" r="6" class="art-dot"/>',
      back_to_school: '<path d="M108 54c0-13 10-23 23-23h64c13 0 23 10 23 23v76H108z"/><path d="M121 54h84m-84 14h84m-84 14h84m-84 14h84m-84 14h84"/><path d="M130 31V21m66 10V21"/><path d="M80 119c-14-9-19-23-9-34 7-7 18-5 24 2l9 12-6 28z"/><path d="M85 86c-3-9 4-15 12-12M47 119c-5-7-4-13 2-17 7 4 9 9 7 16m7-24c-4-7-3-12 3-16 7 4 9 9 6 15"/>',
      holiday_shopping: '<path d="M72 69h176v70H72zM60 51h200v23H60z"/><path d="M160 51v88m0-88c-39 0-43-28-24-30 19-2 24 30 24 30 0-24 12-37 26-29 16 10-2 29-26 29"/><path d="M53 44c31-21 61-22 87-10m40 0c27-12 57-11 88 10" class="art-line"/><circle cx="75" cy="37" r="6" class="art-dot"/><circle cx="227" cy="37" r="6" class="art-dot"/><path d="m160 9 4 8 9 1-7 6 2 9-8-5-8 5 2-9-7-6 9-1z" class="art-fill"/>',
      winter_heating: '<path d="M77 132h166V70H77zM66 70l94-46 94 46"/><path d="M137 132c-20-17-13-35 4-51 1 15 16 15 15 31 9-11 13-19 10-30 25 22 20 41 0 50z" class="art-fill"/><path d="M218 41V25h17v24"/>',
      summer_driving: '<path d="M24 128h272M56 128l48-76h112l48 76"/><path d="M151 67v21m0 18v16" class="art-dash"/><path d="M111 116l10-25h78l14 25v13h-102z"/><circle cx="133" cy="129" r="9"/><circle cx="192" cy="129" r="9"/><circle cx="258" cy="40" r="19" class="art-fill"/>',
      home_garden: '<path d="M45 91 116 36l71 55v49H45zM101 140v-38h31v38"/><path d="M196 136V83m0 31c-29 0-35-17-33-31 20 0 33 10 33 31zm0-16c0-25 15-38 34-39 2 22-9 36-34 39z"/><circle cx="196" cy="70" r="9" class="art-fill"/>',
      work_stoppages: '<path d="M48 130h224M102 130V67m58 63V51m58 79V70"/><circle cx="102" cy="54" r="14"/><circle cx="160" cy="38" r="14"/><circle cx="218" cy="57" r="14"/><path d="M83 96h37m21-8h38m20 11h38"/><path d="M136 75h48v26h-48z" class="art-fill"/><path d="M148 88h24"/>',
      public_trade_filings: '<path d="M97 30h106l31 31v96H97z"/><path d="M203 30v32h31M119 78h87m-87 18h72m-72 18h42"/><path d="m157 128 38-38 13 13-38 38-18 5z" class="art-fill"/><path d="m157 128-5 18 18-5"/><path d="M43 71h39v54H43zM52 82h21m-21 9h21"/><path d="m51 66 38-16 15 42-11 4"/>',
      canada_energy: '<path d="M38 120h244M58 120V91l20-18 20 18v29m128 0V79l27-24 27 24v41"/><path d="M48 120h226v15H48z"/><path d="M126 111V76l20-13 20 13v35m-40-23h40m-26-13v36m13-36v36"/><path d="m239 29 7 14 15-2-10 11 4 15-13-8-13 8 4-15-10-11 15 2z" class="art-fill"/>',
      energy_industry: '<path d="M57 130h206M96 129 135 57l38 72M112 100h47M121 83h37M129 68h29M135 57V39h35"/><path d="M170 39h42m-16 0v20m-10-20v20"/><path d="M221 88c0 21-28 21-28 0 0-11 14-30 14-30s14 19 14 30z" class="art-fill"/><path d="M195 92c7 4 14 4 21 0"/>',
      renewable_power: '<circle cx="79" cy="48" r="22" class="art-fill"/><path d="M79 18V9m0 78v-9M49 48H39m80 0h-10M58 27l-7-7m56 56-7-7m0-42 7-7m-56 56 7-7"/><path d="M190 129V54m0 0L166 39m24 15 22-21m-22 21 2-27M190 77l-32 52m32-52 32 52"/><path d="M54 129h89l-14-26H68zM69 122l6-13m11 13 6-13m11 13 6-13m11 13 6-13"/>',
      precious_metals: '<path d="m66 125 36-26 36 26-36 16zM134 125l36-26 36 26-36 16zM102 99l36-26 36 26-36 16z"/><circle cx="222" cy="67" r="37"/><circle cx="222" cy="67" r="27"/><path d="M222 47v40m-12-29h18l-2 7h-15l-2 8h20"/><path d="M54 64h32m-16-16v32" class="art-line"/>',
      conflict_watch: '<circle cx="158" cy="80" r="55"/><path d="M103 80h110M158 25c-20 17-27 37-27 55s7 38 27 55m0-110c20 17 27 37 27 55s-7 38-27 55"/><path d="M77 117c-20 2-30 16-35 31 16-3 28-10 35-23 9 12 22 19 39 20-5-15-19-28-39-28zm166-5c20 2 30 16 35 31-16-3-28-10-35-23-9 12-22 19-39 20 5-15 19-28 39-28z" class="art-fill"/>',
      tax_refunds: '<path d="M75 41h170v93H75zM75 58l85 45 85-45"/><path d="M206 87h33v38h-33zM215 103h15m-15 9h15"/><path d="M101 83c-12 0-20 8-20 18s8 18 20 18h22c12 0 20-8 20-18s-8-18-20-18z" class="art-fill"/><path d="M112 91v20m-7-15h12l-1 4h-10l-1 4h12"/>',
      crop_progress: '<path d="M38 127h245M61 126V80m39 46V62m39 64V42m42 84V70m44 56V53"/><path d="M61 98c-20-4-28-19-25-34 17 1 27 12 25 34zm0-16c4-19 18-26 34-23-3 16-14 24-34 23zm39 27c-20-5-27-20-23-35 17 2 27 14 23 35zm0-16c5-18 19-25 35-21-4 15-16 23-35 21zm39 2c-19-6-25-22-19-37 16 4 25 17 19 37zm0-18c7-17 22-22 37-16-6 14-18 21-37 16z" class="art-fill"/><path d="M208 48c24-19 50-19 73 0v27h-73zM201 75h87"/>',
      hurricane_season: '<path d="M45 128h230M73 128V98l35-24 35 24v30m-57-20h44m-31 20v-22h19v22"/><path d="M207 43c-16-17-42-8-39 10 3 15 26 15 32 1 9-20-15-37-36-28-31 13-30 57 1 70 31 13 61-13 52-42" class="art-line"/><path d="M215 63c4-22 31-27 39-9 7 15-10 29-24 19-14-11-1-31 16-29"/><path d="M171 112c15-9 31-9 47 0"/>',
      medicare_enrollment: '<path d="M72 40h176v96H72zM72 65h176M111 29v24m97-24v24"/><path d="M96 82h34v34H96zM155 82h34v34h-34zM214 82h20"/><path d="M113 88v22m-11-11h22" class="art-line"/><path d="M169 95c8-12 21-4 18 5-2 7-18 18-18 18s-16-11-18-18c-3-9 10-17 18-5z" class="art-fill"/>',
    };
    const scene = scenes[card.id] || `<circle cx="160" cy="80" r="48"/><text x="160" y="101" text-anchor="middle" class="art-emoji">${escapeHtml(card.icon)}</text>`;
    return `<div class="card-art card-art-${escapeHtml(card.id)}"><svg viewBox="0 0 320 160" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Illustration for ${escapeHtml(card.name)}" xmlns="http://www.w3.org/2000/svg"><title>${escapeHtml(card.name)}</title><g class="art-drawing">${scene}</g></svg><span class="card-art-emblem" aria-hidden="true">${escapeHtml(card.icon)}</span><span class="card-art-caption">${escapeHtml(card.name)}</span><span class="card-art-seal" aria-hidden="true">✳</span></div>`;
  }

  function cardMarkup(card) {
    const metric = card.metrics || {};
    const exposures = (card.research || []).slice(0, 2).map((item) => `<a class="exposure-token" href="${escapeHtml(exposureUrl(item))}" target="_blank" rel="noopener"><b>${escapeHtml(item.ticker || item.name)}</b>${item.ticker ? `<small>${escapeHtml(item.name)}</small>` : ""}</a>`).join("");
    const wisdomNotes = [card.wisdom_note, ...(card.wisdom_extras || [])].filter(Boolean).slice(0, 2);
    const quote = wisdomNotes[0] || { saying: "Read the season; check the evidence.", tradition: "Investor Almanac field note · editor-written", lesson: "A prompt for curiosity, not a market rule." };
    const quotePanel = `<blockquote class="card-flavor">“${escapeHtml(quote.saying)}”</blockquote>`;
    const dynamicNote = "Today’s hand uses the latest available market closes and public releases. Each source updates on its own schedule.";
    const opportunity = card.opportunity || {};
    const readBox = card.metric === "market_averages" ? `<div class="opportunity-box tone-neutral"><span>BUY / SELL READ</span><strong>Market weather · no trade call</strong></div>` : `<div class="opportunity-box tone-${opportunityTone(opportunity.label)}"><span>BUY / SELL READ</span><strong>${escapeHtml(opportunity.label || "No clear signal")}</strong><small>${escapeHtml(opportunity.detail || "The available data does not establish a trade signal.")}</small></div>`;
    const exposureContent = exposures || `<span class="exposure-none">No named examples</span>`;
    const sourceKeys = new Set(card.source_keys || []);
    const allSourceLinks = [
      ...(dashboard?.sources || []).filter((source) => sourceKeys.has(source.source_key)).map((source) => ({ title: source.title, url: source.url })),
      ...(card.reference_links || []),
      ...wisdomNotes.filter((note) => note.url).map((note) => ({ title: `${note.tradition} · wisdom`, url: note.url })),
    ];
    const primarySource = allSourceLinks[0];
    const backSources = [...new Map(allSourceLinks.map((source) => [source.url, source])).values()].map((source) => `<a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.title)} ↗</a>`).join("");
    const backStories = (card.stories || []).slice(0, 2).map((story) => `<div class="reverse-story"><a href="${escapeHtml(story.url)}" target="_blank" rel="noopener">${escapeHtml(story.title)} ↗</a><small>${escapeHtml(story.published || "Recent report")}</small></div>`).join("");
    const metricDetails = (metric.values || []).map((item) => `<div class="reverse-metric-line"><b>${escapeHtml(item.label)}</b><span>${escapeHtml(item.value == null ? "No observation" : `${moneyNumber(item.value, 3)} ${item.unit || ""}`)}${item.years ? ` · ${escapeHtml(item.years)} yr` : ""}${item.change != null ? ` · ${item.change > 0 ? "+" : ""}${escapeHtml(item.change)}%` : ""}</span></div>`).join("");
    const indexDetails = `${(metric.markets || []).map((market) => `<div class="reverse-metric-line"><b>${escapeHtml(market.name)}</b><span>${moneyNumber(market.level, 2)} · ${escapeHtml(market.date)} · ${market.history.map((period) => `${period.years}y ${period.change == null ? "—" : `${period.change > 0 ? "+" : ""}${moneyNumber(period.change, 1)}%`}`).join(" / ")}</span></div>`).join("")}${metric.note ? `<span class="reverse-metric-note">${escapeHtml(metric.note)}</span>` : ""}`;
    const allResearch = (card.research || []).map((item) => `<div class="reverse-research-line"><b><a href="${escapeHtml(exposureUrl(item))}" target="_blank" rel="noopener">${item.ticker ? `${escapeHtml(item.ticker)} · ` : ""}${escapeHtml(item.name)} ↗</a></b><span>${escapeHtml(item.why)}</span></div>`).join("");
    const wisdomResearch = wisdomNotes.map((note) => `<div class="reverse-wisdom"><q>${escapeHtml(note.saying)}</q><span>${escapeHtml(note.tradition)}${note.lesson ? ` · ${escapeHtml(note.lesson)}` : ""}</span></div>`).join("");
    const filingResearch = (card.filing_highlights || []).map((item) => `<div class="reverse-research-line"><b><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)} ↗</a></b><span>${escapeHtml(item.detail)}</span></div>`).join("");
    const opportunityNotes = [opportunity.detail, opportunity.benefit ? `Possible tailwind: ${opportunity.benefit}` : "", opportunity.pressure ? `Possible pressure: ${opportunity.pressure}` : ""].filter(Boolean).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
    const backDisclaimer = card.metric === "conflict_context" ? "War harms people first. Economic effects are possible, not forecasts or direct proxies." : "Research context, not a prediction or personalized investment advice.";
    return `<article class="almanac-card deck-card" data-card="${escapeHtml(card.id)}">
      <div class="card-front">
      <div class="card-top"><span class="live-badge"><i aria-hidden="true"></i> LIVE &amp; DYNAMIC</span><span class="season-tag">${escapeHtml(card.state)}</span></div>
      <p class="eyebrow">${escapeHtml(card.season)} · DEALT FOR THIS SEASON</p><h3>${escapeHtml(card.almanac_title || card.name)}</h3>
      ${cardIllustration(card)}
      <p class="card-lead">${escapeHtml(card.lead)}</p>
      ${quotePanel}
      <section class="card-data-point"><span class="card-section-label">DATA POINT</span><div class="metric-box">${primarySource ? `<a class="metric-source-link" href="${escapeHtml(primarySource.url)}" target="_blank" rel="noopener" aria-label="Open source: ${escapeHtml(primarySource.title)}">` : ""}<strong>${metricText(metric)}</strong>${primarySource ? "</a>" : ""}<span>${escapeHtml(metric.caption || "Official public data")}</span></div></section>
      <div class="card-bottomline">${readBox}<section class="card-exposures"><span class="card-section-label">EXPOSURES</span><div class="exposure-list">${exposureContent}</div></section></div>
      <button class="why-button" type="button" data-flip>Why this connection? <span aria-hidden="true">↗</span></button>
      <small class="card-front-imprint">${escapeHtml(dynamicNote)}</small>
      </div>
      <div class="card-back" aria-hidden="true" inert>
        <div class="card-back-heading"><span>FIELD NOTES · THE REVERSE</span><span class="card-back-mark" aria-hidden="true">✳</span></div>
        <h3>${escapeHtml(card.almanac_title || card.name)}</h3>
        <div class="card-back-observation"><b><span aria-hidden="true">🔎</span> THE OBSERVATION</b>${primarySource ? `<a class="metric-source-link" href="${escapeHtml(primarySource.url)}" target="_blank" rel="noopener">` : ""}<span>${metricText(metric)}</span>${primarySource ? "</a>" : ""}<small>${escapeHtml(metric.caption || "Official public data")}</small>${metricDetails || indexDetails}</div>
        <section class="card-back-section"><b><span aria-hidden="true">🔗</span> WHY IT CONNECTS</b><p>${escapeHtml(card.mechanism)}</p>${opportunity.label ? `<strong class="reverse-read">${escapeHtml(opportunity.label)}:</strong>` : ""}${opportunityNotes}</section>
        <div class="card-back-columns"><section class="card-back-section"><b><span aria-hidden="true">⚖️</span> WHAT COULD CHANGE</b><p>${escapeHtml(card.risks)}</p></section><section class="card-back-research"><b><span aria-hidden="true">🧭</span> ${escapeHtml(card.research_section || "EXPOSURE EXAMPLES")}</b>${allResearch || "<span>No named examples on this card.</span>"}</section></div>
        ${filingResearch ? `<section class="card-back-research reverse-filings"><b><span aria-hidden="true">📜</span> NOTABLE PAPER TRAILS</b>${filingResearch}</section>` : ""}
        ${backStories ? `<section class="card-back-research reverse-stories"><b><span aria-hidden="true">📰</span> ${escapeHtml(card.stories_title || "RECENT REPORTS")}</b>${backStories}</section>` : ""}
        ${wisdomResearch ? `<section class="card-back-wisdom"><b><span aria-hidden="true">🍀</span> FIELD WISDOM</b>${wisdomResearch}</section>` : ""}
        <div class="card-back-footer"><div class="card-back-links">${backSources || "<span>Sources listed in the footer.</span>"}</div><span>${escapeHtml(backDisclaimer)}</span><button type="button" class="card-turn-back" data-flip-back>↶ Return to the card</button></div>
      </div>
    </article>`;
  }

  function layoutDeck() {
    deckCards.forEach((card, index) => {
      const offset = index - deckIndex;
      card.classList.remove("swipe-left", "swipe-right");
      card.inert = offset !== 0;
      card.setAttribute("aria-hidden", offset === 0 ? "false" : "true");
      const flipped = card.classList.contains("is-flipped");
      const front = card.querySelector(".card-front");
      const back = card.querySelector(".card-back");
      front.inert = offset !== 0 || flipped;
      back.inert = offset !== 0 || !flipped;
      front.setAttribute("aria-hidden", offset !== 0 || flipped ? "true" : "false");
      back.setAttribute("aria-hidden", offset !== 0 || !flipped ? "true" : "false");
      card.style.zIndex = String(100 - Math.max(offset, 0));
      card.style.opacity = offset > 2 || offset < 0 ? "0" : "1";
      card.style.pointerEvents = offset === 0 ? "auto" : "none";
      card.style.transform = offset < 0 ? "translateX(-140%) rotate(-10deg)" : `translateY(${offset * 7}px) scale(${1 - offset * 0.025})`;
    });
    const done = deckIndex >= deckCards.length;
    $("#deck-position").textContent = done ? `${deckCards.length} cards explored` : `Card ${deckIndex + 1} of ${deckCards.length}`;
    $("#deck-prev").disabled = deckIndex <= 0;
    $("#deck-next").disabled = done;
    $("#empty-state").hidden = deckCards.length > 0 && !done;
    if (done && deckCards.length) $("#empty-state").textContent = "That’s the deck for now. Go back to revisit a card, or refresh data for an update.";
  }

  function moveDeck(direction, exitRight = false) {
    if (direction < 0) {
      deckIndex = Math.max(0, deckIndex - 1);
      layoutDeck();
      return;
    }
    if (deckIndex >= deckCards.length) return;
    const top = deckCards[deckIndex];
    top.classList.add(exitRight ? "swipe-right" : "swipe-left");
    clearTimeout(deckTimer);
    deckTimer = setTimeout(() => {
      deckIndex = Math.min(deckIndex + 1, deckCards.length);
      layoutDeck();
    }, 250);
  }

  function showCards() {
    if (!dashboard) return;
    let cards = dashboard.cards;
    if (activeView === "today") {
      const selected = new Set(dashboard.featured_ids);
      cards = cards.filter((card) => selected.has(card.id));
    } else if (activeView === "month") {
      cards = cards.filter((card) => !card.start || dashboard.calendar[activeMonth].some((entry) => entry.id === card.id));
    } else {
      cards = [];
    }
    const previousId = deckCards[deckIndex]?.dataset.card;
    const previousWasFlipped = Boolean(deckCards[deckIndex]?.classList.contains("is-flipped"));
    cardsHost.innerHTML = cards.map(cardMarkup).join("");
    deckCards = [...cardsHost.querySelectorAll(".deck-card")];
    const preservedIndex = previousId ? deckCards.findIndex((card) => card.dataset.card === previousId) : -1;
    deckIndex = preservedIndex >= 0 ? preservedIndex : 0;
    if (previousWasFlipped && deckCards[deckIndex]) deckCards[deckIndex].classList.add("is-flipped");
    cardsHost.classList.toggle("swipe-deck", activeView !== "year");
    $("#deck-controls").hidden = activeView === "year" || cards.length === 0;
    $("#empty-state").hidden = cards.length > 0 || activeView === "year";
    $("#year-view").hidden = activeView !== "year";
    $(".almanac-section").hidden = activeView === "year";
    $("#cards-title").textContent = activeView === "today" ? "The cards today dealt you" : activeView === "month" ? `The cards ${monthName(activeMonth)} dealt you` : "A year of little seasons";
    document.querySelectorAll(".nav-view").forEach((button) => button.classList.toggle("active", button.dataset.view === activeView));
    if (activeView !== "year" && cards.length) layoutDeck();
  }

  function renderYear() {
    const host = $("#year-grid");
    host.innerHTML = Array.from({ length: 12 }, (_, index) => {
      const month = index + 1;
      const entries = dashboard.calendar[month] || [];
      return `<button class="month-card" type="button" data-month="${month}"><strong>${monthName(month)}</strong><span>${entries.length ? entries.map((entry) => `${escapeHtml(entry.icon)} ${escapeHtml(entry.name)}`).join(" · ") : "A quiet patch"}</span></button>`;
    }).join("");
  }

  function renderSources() {
    const host = $("#source-list");
    host.innerHTML = dashboard.sources.map((source) => {
      const state = source.last_error ? "Update needs attention" : source.retrieved_at ? `Updated ${new Date(source.retrieved_at).toLocaleString()}` : "Waiting for first download";
      return `<p><a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.title)}</a><br><small>${escapeHtml(state)}${source.last_error ? ` · ${escapeHtml(source.last_error)}` : ""}</small></p>`;
    }).join("");
    const cached = dashboard.sources.filter((source) => source.retrieved_at).length;
    $("#source-line").textContent = `${cached} of ${dashboard.sources.length} public sources cached`;
    const refresh = dashboard.refresh || {};
    const attention = dashboard.sources.filter((source) => source.last_error).length;
    const check = $("#source-health");
    if (check) {
      const state = refresh.running ? "Refresh in progress" : attention ? `${attention} source${attention === 1 ? "" : "s"} need attention` : cached ? "Sources responding" : "Waiting for first download";
      const updated = refresh.finished_at ? ` · Last check ${new Date(refresh.finished_at).toLocaleString()}` : "";
      check.textContent = `${state}${updated}`;
      check.classList.toggle("is-warning", Boolean(attention));
    }
  }

  function renderStatus() {
    const status = dashboard.refresh;
    const host = $("#status");
    // Per-source freshness and failures are listed in the footer; avoid duplicating
    // them in an aggregate banner above the card deck.
    host.hidden = true;
    host.classList.toggle("is-error", !status.running && status.errors?.length > 0 && dashboard.sources.every((source) => !source.retrieved_at));
    $("#refresh-button").disabled = Boolean(status.running);
    $("#refresh-button").classList.toggle("is-loading", Boolean(status.running));
  }

  function render() {
    if (!dashboard) return;
    $("#today-date").textContent = dashboard.pretty_date.toUpperCase();
    renderYear();
    renderSources();
    renderStatus();
    showCards();
  }

  async function loadDashboard() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch("/api/dashboard", { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`Dashboard request failed (${response.status})`);
      const payload = await response.json();
      if (!Array.isArray(payload.cards) || !Array.isArray(payload.featured_ids)) {
        throw new Error("The server returned an older dashboard format. Rebuild the container from the matching project files.");
      }
      dashboard = payload;
      dashboardRetryAttempt = 0;
      activeMonth ??= dashboard.month;
      render();
      if (dashboard.refresh.running) setTimeout(loadDashboard, 2500);
    } catch (error) {
      dashboardRetryAttempt += 1;
      const delay = Math.min(30000, 1000 * (2 ** Math.min(dashboardRetryAttempt - 1, 5)));
      const reason = error.name === "AbortError" ? "The dashboard request timed out." : error.message;
      $("#status").hidden = false;
      $("#status").textContent = `${reason} Retrying automatically in ${Math.ceil(delay / 1000)} seconds…`;
      $("#status").classList.add("is-error");
      $("#sources-drawer").open = true;
      $("#refresh-button").disabled = false;
      setTimeout(loadDashboard, delay);
    } finally {
      clearTimeout(timeout);
    }
  }

  document.addEventListener("click", (event) => {
    const nav = event.target.closest("[data-view]");
    const flip = event.target.closest("[data-flip]");
    const flipBack = event.target.closest("[data-flip-back]");
    const month = event.target.closest("[data-month]");
    const prev = event.target.closest("#deck-prev");
    const next = event.target.closest("#deck-next");
    if (prev) moveDeck(-1);
    if (next) moveDeck(1);
    if (nav) { activeView = nav.dataset.view; showCards(); }
    if (flip || flipBack) {
      const card = (flip || flipBack).closest(".deck-card");
      card.classList.toggle("is-flipped", Boolean(flip));
      const front = card.querySelector(".card-front");
      const back = card.querySelector(".card-back");
      front.inert = Boolean(flip);
      back.inert = !flip;
      front.setAttribute("aria-hidden", flip ? "true" : "false");
      back.setAttribute("aria-hidden", flip ? "false" : "true");
    }
    if (month) { activeMonth = Number(month.dataset.month); activeView = "month"; showCards(); window.scrollTo({ top: 0, behavior: "smooth" }); }
  });
  cardsHost.addEventListener("pointerdown", (event) => {
    const top = deckCards[deckIndex];
    if (!top || !top.contains(event.target) || event.target.closest("a, button")) return;
    dragState = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, deltaX: 0, card: top };
    top.style.transition = "none";
    try { top.setPointerCapture(event.pointerId); } catch (_) {}
  });
  cardsHost.addEventListener("pointermove", (event) => {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const deltaY = event.clientY - dragState.startY;
    const deltaX = event.clientX - dragState.startX;
    if (Math.abs(deltaY) > 10 && Math.abs(deltaY) > Math.abs(deltaX)) {
      const card = dragState.card;
      dragState = null;
      card.style.transition = "";
      layoutDeck();
      return;
    }
    dragState.deltaX = deltaX;
    dragState.card.style.transform = `translateX(${dragState.deltaX}px) rotate(${dragState.deltaX * 0.035}deg)`;
  });
  const endSwipe = (event) => {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const { card, deltaX } = dragState;
    dragState = null;
    card.style.transition = "";
    if (Math.abs(deltaX) > 85) moveDeck(1, deltaX > 0);
    else layoutDeck();
  };
  cardsHost.addEventListener("pointerup", endSwipe);
  cardsHost.addEventListener("pointercancel", endSwipe);
  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea, select")) return;
    if (event.key === "ArrowRight") { event.preventDefault(); moveDeck(1); }
    if (event.key === "ArrowLeft") { event.preventDefault(); moveDeck(-1); }
  });
  $("#refresh-button").addEventListener("click", async () => {
    const button = $("#refresh-button");
    button.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch("/api/refresh", { method: "POST", signal: controller.signal });
      if (!response.ok) throw new Error(`Refresh request failed (${response.status})`);
      await loadDashboard();
    } catch (error) {
      $("#status").hidden = false;
      $("#status").textContent = error.name === "AbortError" ? "Refresh request timed out. Retrying the dashboard connection…" : `Refresh could not start: ${error.message}`;
      $("#status").classList.add("is-error");
      button.disabled = false;
      setTimeout(loadDashboard, 1500);
    } finally {
      clearTimeout(timeout);
    }
  });
  $("#status").textContent = "Connecting to the dashboard…";
  loadDashboard();
})();
