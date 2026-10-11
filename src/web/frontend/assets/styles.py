"""Stylesheet for the catalog page and the saved report."""

CSS = """
    :root {
      color-scheme: light;
      --ink: #1c1915;
      --muted: #5e584f;
      --line: #e4ddd2;
      --paper: #f6f3ee;
      --card: #fffcf8;
      --green: #0d6b52;
      --green-soft: #e5f4ef;
      --amber: #8a5a12;
      --amber-soft: #f8efdc;
      --red: #8a2b24;
      --red-soft: #f6e4e1;
      --blue: #2a4f94;
      --blue-soft: #e6eefb;
      --gold: #c58a00;
      --viewed: #eeebe4;
      --viewed-hover: #e8e4dc;
    }
    * { box-sizing: border-box; }
    html { -webkit-text-size-adjust: 100%; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 16px/1.45 "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    }
    main { max-width: 1100px; margin: 0 auto; padding: 28px 20px 64px; }
    .topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
    .who { display: flex; align-items: center; gap: 10px; flex: none; margin-left: auto; }
    .account { display: flex; align-items: center; gap: 8px; }
    .account .name {
      font-size: 0.9rem; color: var(--muted); max-width: 12rem;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .account button.secondary { padding: 4px 10px; }
    .auth { max-width: 28rem; }
    .auth label { margin-bottom: 12px; }
    .auth input { width: 100%; }
    .auth .switch { margin: 16px 0 0; }
    :focus-visible { outline: 2px solid var(--green); outline-offset: 2px; }
    h1 { font-size: 1.7rem; line-height: 1.2; margin: 0 0 8px; }
    .langs { display: flex; gap: 2px; flex: none; font-size: 0.85rem; }
    .langs a {
      padding: 4px 9px; border: 1px solid var(--line); background: var(--card);
      color: var(--muted); text-decoration: none;
    }
    .langs a:first-child { border-radius: 8px 0 0 8px; }
    .langs a:last-child { border-radius: 0 8px 8px 0; }
    .langs a[aria-current="true"] { background: var(--green); border-color: var(--green); color: white; }
    .lede { color: var(--muted); margin: 0 0 20px; max-width: 68ch; }
    .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
    }
    form.bare { background: none; border: 0; padding: 0; margin: 0; }
    summary { cursor: pointer; font-weight: 600; padding: 2px 0; }
    details[open] > summary { margin-bottom: 12px; }
    summary .badge { margin-left: 6px; font-weight: 500; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
    label { display: flex; flex-direction: column; gap: 4px; font-size: 0.82rem; color: var(--muted); }
    input, select {
      font: inherit; color: var(--ink); background: white;
      border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px;
    }
    .options { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
    label.checks {
      flex-direction: row;
      align-items: flex-start;
      gap: 8px;
      color: var(--ink);
      font-size: 0.95rem;
    }
    label.checks input { width: 1rem; height: 1rem; margin: 3px 0 0; }
    button, .button {
      background: var(--green); color: white; border: 0; border-radius: 8px;
      padding: 10px 16px; font: inherit; cursor: pointer; text-decoration: none;
      display: inline-block; line-height: 1.2;
    }
    button.secondary, .button.secondary {
      background: transparent; color: var(--green); border: 1px solid var(--green);
    }
    button:disabled { opacity: 0.55; cursor: default; }
    .sources { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 12px; padding: 0; list-style: none; }
    .sources li {
      display: inline-flex; align-items: center; gap: 6px;
      background: var(--card); border: 1px solid var(--line); border-radius: 999px;
      padding: 4px 10px; font-size: 0.85rem; white-space: nowrap;
    }
    .sources .bad { border-color: #e7b4b4; background: #fdecec; }
    .sources .warn { border-color: #e7d3a8; background: var(--amber-soft); }
    .banner {
      background: var(--amber-soft); color: var(--amber);
      border-radius: 10px; padding: 10px 12px; margin: 0 0 12px;
    }
    .banner.problem { background: #fdecec; color: var(--red); }
    .toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin: 8px 0; }
    .count, .statusline { color: var(--muted); }
    .statusline { margin: 0 0 12px; }
    .statusline a.stat { color: inherit; text-decoration-style: dotted; text-underline-offset: 3px; }
    .actions { display: flex; gap: 8px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
    .legend-box { margin: 0 0 10px; }
    .legend-box > summary { font-size: 0.82rem; font-weight: 500; color: var(--muted); }
    .legend-box[open] > summary { margin-bottom: 6px; }
    .legend {
      display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 0; padding: 0;
      list-style: none; font-size: 0.82rem; color: var(--muted);
    }
    .legend li { display: inline-flex; align-items: center; gap: 6px; }
    .legend .swatch { width: 14px; height: 14px; border-radius: 4px; border: 1px solid var(--line); }
    .swatch.sw-new { background: var(--green); border-color: var(--green); }
    .swatch.sw-changed { background: #d99a22; border-color: #d99a22; }
    .swatch.sw-closed { background: #b4655d; border-color: #b4655d; }
    .swatch.sw-viewed { background: var(--viewed); }
    .swatch.sw-en {
      width: auto; height: auto; padding: 0 5px; background: var(--blue-soft);
      color: var(--blue); border-color: var(--blue-soft); font-size: 0.7rem; font-weight: 700;
    }
    .table-wrap { border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
    tbody tr[hidden] { display: none; }
    table { width: 100%; border-collapse: collapse; background: var(--card); }
    caption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
    th, td { text-align: left; padding: 12px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
    th {
      position: sticky; top: 0; z-index: 1;
      font-size: 0.78rem; letter-spacing: 0.03em; text-transform: uppercase; color: var(--muted);
      background: var(--card);
    }
    th a.sort { color: inherit; text-decoration: none; white-space: nowrap; cursor: pointer; }
    th a.sort:hover { text-decoration: underline; }
    th a.sort .idle { opacity: 0.45; }
    th[aria-sort] a.sort { color: var(--green); }
    tr:last-child td { border-bottom: 0; }
    tbody tr { --mark: transparent; }
    tbody tr:hover { background: #f4f8f6; }
    td.when { box-shadow: inset 4px 0 0 var(--mark); }
    td.when, td.pay { white-space: nowrap; }
    td.where { max-width: 16rem; }
    /* What the last refresh did: the coloured edge, and a tag next to the title. */
    tr.is-new { --mark: var(--green); }
    tr.is-changed { --mark: #d99a22; }
    tr.closed { --mark: #b4655d; opacity: 0.6; }
    /* A job you already opened. */
    tr.viewed { background: var(--viewed); }
    tr.viewed:hover { background: var(--viewed-hover); }
    tr.viewed .title { color: var(--muted); font-weight: 500; }
    tr.is-hidden { opacity: 0.5; }
    tr.is-hidden .title { text-decoration: line-through; }
    a { color: var(--green); }
    .title { font-weight: 600; }
    .meta { color: var(--muted); font-size: 0.88rem; margin-top: 3px; }
    .meta a.board { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
    .meta a.board:hover { color: var(--green); }
    .badge {
      display: inline-block; border-radius: 999px; padding: 1px 8px;
      background: var(--green-soft); color: var(--green); font-size: 0.78rem;
    }
    .badge.warn { background: var(--amber-soft); color: var(--amber); }
    .tag {
      display: inline-block; margin-left: 6px; border-radius: 999px; padding: 0 7px;
      font-size: 0.72rem; font-weight: 700; vertical-align: 1px; white-space: nowrap;
    }
    .tag-new { background: var(--green-soft); color: var(--green); }
    .tag-changed { background: var(--amber-soft); color: var(--amber); }
    .tag-closed { background: var(--red-soft); color: var(--red); }
    .chip-en {
      display: inline-block; margin-left: 6px; border-radius: 6px; padding: 0 6px;
      background: var(--blue-soft); color: var(--blue); font-size: 0.72rem; font-weight: 700;
      letter-spacing: 0.04em;
    }
    .empty { color: var(--muted); padding: 24px 10px; }
    .note { color: var(--muted); font-size: 0.9rem; max-width: 78ch; }
    .links { padding-left: 18px; }
    #filter { max-width: 280px; }

    /* Marks: favorite, not for me, viewed, and a rating. */
    td.mine { white-space: nowrap; }
    .acts { display: flex; gap: 6px; }
    .stars { display: flex; margin-top: 4px; }
    button.act, button.star {
      background: transparent; color: var(--muted); border: 1px solid var(--line);
      padding: 0; line-height: 1; font-variant-emoji: text;
    }
    button.act {
      width: 30px; height: 30px; border-radius: 50%; font-size: 0.95rem; background: var(--card);
    }
    button.star {
      width: 22px; height: 24px; border: 0; border-radius: 4px; font-size: 1.05rem;
      color: #d4cbbd;
    }
    button.star.on { color: var(--gold); }
    button.act:hover, button.star:hover { border-color: var(--green); }
    button.star:hover { color: var(--gold); }
    button.act.fav[aria-pressed="true"] { color: #b3261e; border-color: #e3aaa6; background: #fbeceb; }
    button.act.hide[aria-pressed="true"] { color: white; background: #6b665e; border-color: #6b665e; }
    button.act.seen[aria-pressed="true"] { color: var(--green); border-color: #9fd0c0; background: var(--green-soft); }
    button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible {
      outline: 2px solid #1a73e8; outline-offset: 2px;
    }

    /* Pages and "show more". */
    .paging { display: flex; flex-direction: column; align-items: center; gap: 12px; margin: 16px 0; }
    .pager { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 6px; }
    .pager a, .pager span.gap {
      min-width: 36px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 8px;
      background: var(--card); color: var(--ink); text-decoration: none; text-align: center;
      font-size: 0.92rem;
    }
    .pager span.gap { border-color: transparent; background: none; color: var(--muted); }
    .pager a[aria-current="page"] { background: var(--green); border-color: var(--green); color: white; }
    .pager a[aria-disabled="true"] { opacity: 0.45; pointer-events: none; }
    .pager .where-label { display: none; color: var(--muted); font-size: 0.9rem; }
    #more[hidden], .pager[hidden] { display: none; }
    #toast {
      position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); z-index: 10;
      display: flex; align-items: center; gap: 14px; max-width: calc(100vw - 24px);
      background: #2a2722; color: white; border-radius: 10px; padding: 10px 14px;
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
    }
    #toast[hidden] { display: none; }
    #toast button { background: transparent; color: #9fe0c8; padding: 2px 4px; font-weight: 600; }

    /* Wide screens: use the room. */
    @media (min-width: 1500px) {
      main { max-width: 1320px; }
      td.where { max-width: 22rem; }
    }

    /* Tablets and small laptops: the same table, tighter, and it scrolls instead of clipping. */
    @media (max-width: 960px) {
      main { padding: 22px 16px 56px; }
      .table-wrap { overflow-x: auto; }
      th, td { padding: 10px 8px; }
      td.where { max-width: 12rem; }
      .grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); }
    }

    /* Phones: each vacancy is a card. */
    @media (max-width: 640px) {
      main {
        padding: 16px max(12px, env(safe-area-inset-right)) 48px max(12px, env(safe-area-inset-left));
      }
      h1 { font-size: 1.35rem; }
      .topbar { flex-direction: column; align-items: stretch; }
      .who { margin-left: 0; justify-content: space-between; }
      .account .name { max-width: 9rem; }
      .lede { font-size: 0.95rem; margin-bottom: 14px; }
      .panel { padding: 12px; border-radius: 10px; }
      .grid { grid-template-columns: 1fr; gap: 10px; }
      .actions button, .actions .button { flex: 1 1 100%; text-align: center; }
      .actions form { flex: 1 1 100%; }
      .actions form button { width: 100%; }
      .sources {
        flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px;
        margin-right: -12px; padding-right: 12px; scrollbar-width: none;
      }
      .sources::-webkit-scrollbar { display: none; }
      .sources li { flex: none; }
      .toolbar { flex-direction: column; align-items: stretch; gap: 8px; }
      #filter { max-width: none; width: 100%; }
      .table-wrap { border: 0; background: none; border-radius: 0; overflow: visible; }
      table, thead, tbody { display: block; background: none; }
      thead { margin-bottom: 10px; }
      thead tr { display: flex; flex-wrap: wrap; gap: 8px; }
      thead th {
        display: none; position: static; padding: 0; border: 0; background: none;
        text-transform: none; letter-spacing: 0;
      }
      thead th:has(a.sort) { display: block; }
      th a.sort {
        display: inline-flex; align-items: center; min-height: 44px; padding: 0 12px;
        border: 1px solid var(--line); border-radius: 999px; background: var(--card);
        font-size: 0.92rem;
      }
      th[aria-sort] a.sort { border-color: var(--green); background: var(--green-soft); }
      table.static thead { display: none; }
      tbody tr {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        grid-template-areas:
          "job job"
          "company status"
          "where where"
          "pay when"
          "mine mine";
        gap: 6px 12px;
        background: var(--card); border: 1px solid var(--line); border-radius: 12px;
        border-left: 5px solid var(--mark);
        padding: 12px; margin-bottom: 10px;
      }
      table.static tbody tr {
        grid-template-areas: "job job" "company status" "where where" "pay when";
      }
      tbody tr:hover { background: var(--card); }
      tbody tr.viewed, tbody tr.viewed:hover { background: var(--viewed); }
      tbody tr:last-child td { border-bottom: 0; }
      td { display: block; padding: 0; border: 0; min-width: 0; overflow-wrap: anywhere; }
      td.when { box-shadow: none; }
      td.job { grid-area: job; }
      td.company { grid-area: company; font-weight: 600; }
      td.status { grid-area: status; text-align: right; }
      td.where { grid-area: where; max-width: none; color: var(--muted); font-size: 0.92rem; }
      td.pay { grid-area: pay; white-space: normal; }
      td.pay.none { display: none; }
      td.when { grid-area: when; text-align: right; color: var(--muted); font-size: 0.85rem; }
      td.mine {
        grid-area: mine; display: flex; align-items: center; justify-content: space-between;
        gap: 10px; padding-top: 8px; border-top: 1px solid var(--line);
      }
      .stars { margin-top: 0; }
      td.empty { grid-area: auto; grid-column: 1 / -1; padding: 16px 4px; }
      tbody tr:has(td.empty) { display: block; border: 0; background: none; padding: 0; }
      .title { font-size: 1.02rem; line-height: 1.3; }
      .pager .num { display: none; }
      .pager .where-label { display: inline; }
      #toast { left: 12px; right: 12px; transform: none; max-width: none; justify-content: space-between; }
    }

    /* Touch screens: bigger targets, whatever the width. */
    @media (pointer: coarse) {
      input:not([type="checkbox"]), select, button:not(.act):not(.star) { min-height: 44px; }
      label.checks { padding: 4px 0; }
      label.checks input { width: 1.3rem; height: 1.3rem; margin-top: 1px; }
      button.act { width: 40px; height: 40px; }
      button.star { width: 34px; height: 40px; font-size: 1.3rem; }
      .pager a { min-height: 44px; display: inline-flex; align-items: center; justify-content: center; }
    }

    /* Sign-in and registration sit in a narrow column in the middle of the page. */
    .auth-page {
      min-height: 100vh;
      min-height: 100dvh;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .auth-page main {
      width: 100%;
      max-width: 28rem;
      padding-top: 24px;
      padding-bottom: 24px;
    }
    .auth-page .auth { max-width: none; }
    .auth-page .lede, .auth-page .note { max-width: none; }
    @media (max-width: 640px) {
      .auth-page .topbar { flex-direction: row; align-items: flex-start; }
    }
"""
