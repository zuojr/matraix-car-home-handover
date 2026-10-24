import { describe, expect, it } from "vitest";

import {
  createLocalePackLoader,
  loadLocaleWithFallback,
} from "../loader";
import { getLocaleDefinition, LOCALE_REGISTRY } from "../registry";
import { SOURCE_LOCALE, SOURCE_MESSAGES, withEnglishFallback } from "../source";

function readBalancedBlock(value: string, start: number): { body: string; end: number } {
  let depth = 0;
  for (let index = start; index < value.length; index += 1) {
    if (value[index] === "{") depth += 1;
    if (value[index] === "}") {
      depth -= 1;
      if (depth === 0) return { body: value.slice(start + 1, index), end: index + 1 };
      if (depth < 0) throw new Error("Unexpected closing ICU brace");
    }
  }
  throw new Error(`Unbalanced ICU block in ${value}`);
}

function splitTopLevel(input: string, delimiter: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;

  for (let index = 0; index < input.length; index += 1) {
    if (input[index] === "{") {
      depth += 1;
    } else if (input[index] === "}") {
      depth -= 1;
      if (depth < 0) throw new Error("Unexpected closing ICU brace");
    } else if (input[index] === delimiter && depth === 0) {
      parts.push(input.slice(start, index));
      start = index + 1;
    }
  }

  if (depth !== 0) throw new Error("Unclosed ICU brace while splitting a block");
  parts.push(input.slice(start));
  return parts;
}

function controlBranchLabels(value: string): Array<{ label: string; body: string }> {
  const branches: Array<{ label: string; body: string }> = [];
  let index = 0;
  while (index < value.length) {
    while (index < value.length && /[\s,]/.test(value[index])) index += 1;
    const match = /^([^\s{,]+)\s*\{/.exec(value.slice(index));
    if (!match) break;
    const block = readBalancedBlock(value, index + match[0].lastIndexOf("{"));
    branches.push({ label: match[1], body: block.body });
    index = block.end;
  }
  if (branches.length === 0) throw new Error("Choice formatter must contain branches");
  return branches;
}

function recordRichTags(value: string, signature: string[]): void {
  const stack: string[] = [];
  for (const match of value.matchAll(/<\/?([A-Za-z][\w-]*)(?:\s[^<>]*?)?\/?\s*>/g)) {
    const token = match[0];
    const name = match[1];
    signature.push(`tag:${token}`);
    if (token.startsWith("</")) {
      if (stack.pop() !== name) throw new Error(`Misnested rich-text tag: ${token}`);
    } else if (!/\/\s*>$/.test(token)) {
      stack.push(name);
    }
  }
  if (stack.length > 0) throw new Error(`Unclosed rich-text tag: ${stack[stack.length - 1]}`);
}

function icuSignature(value: string): string[] {
  const signature: string[] = [];
  const visit = (message: string): void => {
    for (let index = 0; index < message.length; index += 1) {
      if (message[index] !== "{") continue;
      const block = readBalancedBlock(message, index);
      const parts = splitTopLevel(block.body, ",").map((part) => part.trim());
      const argument = parts[0];
      const format = parts[1] ?? "bare";
      if (["plural", "select", "selectordinal"].includes(format)) {
        const controlBody = parts.slice(2).join(",");
        const offsetMatch = controlBody.match(/^offset\s*:\s*(\d+)\b/);
        const offset = format === "select" ? 0 : Number(offsetMatch?.[1] ?? 0);
        const branches = controlBranchLabels(offsetMatch ? controlBody.slice(offsetMatch[0].length) : controlBody);
        const branchShapes = branches.map(
          ({ label, body }) => `${label}:${JSON.stringify(icuSignature(body))}`,
        );
        signature.push(
          `control:${argument}:${format}:offset=${offset}:${branchShapes.join(",")}`,
        );
      } else if (/^[A-Za-z_][\w.-]*$/.test(argument)) {
        const style = parts.slice(2).join(",").trim();
        signature.push(`arg:${argument}:${format}:${style}`);
      }
      index = block.end - 1;
    }
  };
  visit(value);
  const tags: string[] = [];
  recordRichTags(value, tags);
  return [...signature.sort(), ...tags];
}

function expectMessages(
  pack: object,
  expected: Readonly<Record<string, string>>,
): void {
  const messages = pack as Record<string, string | undefined>;
  for (const [key, value] of Object.entries(expected)) {
    expect(messages[key]).toBe(value);
  }
}

describe("zh-Hant locale pack", () => {
  it("is registered as a machine-assisted lazy optional locale", async () => {
    const definition = getLocaleDefinition("zh-Hant");

    expect(definition).toMatchObject({
      code: "zh-Hant",
      nativeName: "繁體中文",
      englishName: "Traditional Chinese",
      dir: "ltr",
      fallback: "en-US",
      translationStatus: "machine-assisted",
    });
    expect(definition.load.toString()).toContain("zh-Hant.json");
    expect(definition.load.toString()).toMatch(/import|dynamic_import/);

    const loaded = await definition.load();
    expect(loaded["shell.nav.home"]).toBe("首頁");
  });

  it("contains exactly the current English key set and no obsolete keys", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    expect(Object.keys(pack).sort()).toEqual(Object.keys(SOURCE_MESSAGES).sort());
    expect(Object.keys(pack).some((key) => !(key in SOURCE_MESSAGES))).toBe(false);
  });

  it("loads through the registry fallback chain and falls back to English", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const partialPack = { ...pack };
    delete partialPack["locale.english"];
    const definitions = LOCALE_REGISTRY.map((definition) =>
      definition.code === "zh-Hant" ? { ...definition, load: async () => partialPack } : definition,
    );
    const loader = createLocalePackLoader(definitions, new Map([[SOURCE_LOCALE, SOURCE_MESSAGES]]));
    const merged = await loadLocaleWithFallback("zh-Hant", definitions, loader);

    expect(merged["locale.current"]).toBe("目前語言");
    expect(merged["locale.english"]).toBe("English");
    expect(withEnglishFallback(partialPack)["locale.english"]).toBe("English");
  });

  it("preserves ICU arguments, formatter branches, and rich-text tags", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const sourceKeys = Object.keys(SOURCE_MESSAGES) as Array<keyof typeof SOURCE_MESSAGES>;
    for (const key of sourceKeys) {
      expect(icuSignature(pack[key] ?? ""), key).toEqual(icuSignature(SOURCE_MESSAGES[key]));
    }
  });

  it("rejects ICU and rich-text shape mutations", () => {
    expect(icuSignature("{count}")).not.toEqual(icuSignature("{count, number}"));
    expect(icuSignature("{value, date}")).not.toEqual(icuSignature("{value, time}"));
    expect(icuSignature("{status, select, one {A} other {B}}"))
      .not.toEqual(icuSignature("{status, select, one {A} archived {B}}"));
    expect(icuSignature("{count, plural, offset:1 one {# item} other {# items}}"))
      .not.toEqual(icuSignature("{count, plural, offset:2 one {# item} other {# items}}"));
    expect(icuSignature("{count, plural, one {Hi {name}} other {None}}"))
      .not.toEqual(icuSignature("{count, plural, one {Hi {otherName}} other {None}}"));
    expect(() => icuSignature("<a><b>{value}</a></b>")).toThrow();
    expect(icuSignature("{status, select, one {Hi {name}} other {None}}"))
      .not.toEqual(icuSignature("{status, select, one {Hi} other {None {name}}}"));
    expect(icuSignature("{value, number, ::currency/USD}"))
      .not.toEqual(icuSignature("{value, number, ::percent}"));
  });

  it("translates representative shell, sampling, safety, empty-state, and report copy", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["shell.nav.home"]).toBe("首頁");
    expect(pack["locale.buttonLabel"]).toBe("變更語言");
    expect(pack["personaSetup.filters.stratifyHint"]).toContain("分層");
    expect(pack["cockpitSetup.run.stopRun"]).toBe("停止執行");
    expect(pack["runs.deleteConfirm"]).toContain("刪除");
    expect(pack["runs.emptyDescription"]).toContain("<path>jobs/</path>");
    expect(pack["reports.usage.costTitle"]).toContain("LLM 成本");
    expect(pack["scorecards.scale.legend"]).toContain("<green>");
    expect(pack["scorecards.scale.legend"]).toContain("<red>");
  });

  it("uses exact Taiwan wording for high-risk copy", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const expected = {
      "shell.home.titleAccent": "數位人",
      "structuredExposure.top": "排名第一",
      "personaSetup.filters.apply": "套用篩選條件",
      "reports.facet.policyCheck": "政策合規檢查",
      "reports.bucket.policyGuardrail": "來自政策合規檢查",
      "reports.context.policyAndTrust": "政策與信任",
      "reports.context.policyAndTrustDescription": "對依據充分性、政策合規性與交接品質的檢查。",
      "reports.bucket.fail": "未通過",
      "taskScorecard.fail": "未通過",
      "reports.bucket.pass": "通過",
      "reports.bucket.passed": "通過",
      "taskScorecard.pass": "通過",
      "taskScorecard.passed": "通過",
      "runs.passedChecks": "檢查通過",
      "shell.preflight.allChecksPassed": "所有檢查均已通過。",
      "taskSetup.status.chatApiReady": "聊天 API 已就緒（能力檢查通過）。",
      "reports.page.oneConversation": "每個數位人各有一次對話 — 開啟任一項即可查看完整記錄",
      "reports.report.present": "有值",
      "reports.report.presentCount": "{count} 筆有值",
      "reports.bucket.sharedWorld": "共享控制",
      "reports.bucket.grounding": "無法基於 UI 提供依據",
      "reports.pdf.playground": "Playground",
      "shell.nav.playground": "Playground",
      "reports.analysis.the": "未註明",
      "reports.analysis.signalFrequency": "每個訊號在已評分{sampleLabel}中的出現頻率（樣本數：{count}；僅表示占比，不代表品質評分）",
    } as const;

    expectMessages(pack, expected);
  });

  it("uses Taiwan terminology for cohort, live, and report chrome", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["cockpitSetup.batch.simulatedCohort"]).toBe("模擬群組");
    expect(pack["personaSetup.loadingCohort"]).toBe("正在載入群組…");
    expect(pack["cockpitSetup.run.liveHint"]).toContain("即時");
    expect(pack["shell.nav.application"]).toBe("應用程式導覽");
    expect(pack["reports.analysis.signalFrequency"]).toContain("品質評分");
    expect(pack["personaSetup.strategy.custom"]).toBe("自訂");
    expect(pack["personaSetup.datasetReuse"]).toContain("重複使用");
    expect(pack["reports.report.distributionExplanation"]).toContain("儲存格");
    expect(pack["reports.feedback.personaOwnWords"]).toContain("聊天後");

    expect(
      Object.values(pack).some((value) =>
        /(后|質量|自定義|複用|單元格|覆盤|當前|分段|客戶分組|佇列|(?<!數位)人群|實時|導航|畫像|自報告|[“”])/u.test(
          value ?? "",
        ),
      ),
    ).toBe(false);
  });

  it("uses catalog persona and context terminology", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["catalog.personaCard.demographicsTitle"]).toBe("年齡 · 性別 · Persona ID");
    expect(pack["catalog.personaCatalog.eyebrow"]).toBe("數位人目錄");
    expect(pack["catalog.personaPanel.context"]).toBe("情境");
    expect(pack["catalog.personaStore.showing"]).toBe("顯示 {shown} / {total} — 向下捲動查看更多");
  });

  it("uses cockpit Taiwan terminology", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["cockpit.environment.default.personaPrompt"]).toBe("來自 Playground 的數位人提示詞");
    expect(pack["cockpit.environment.personaDefault"]).toBe("數位人預設模型");
    expect(pack["cockpit.harbor.play"]).toBe("播放軌跡重播");
    expect(pack["cockpit.inspector.context"]).toBe("情境");
    expect(pack["cockpit.session.newChat"]).toBe("新增對話");
    expect(pack["cockpit.taskType.osApp"]).toBe("OS 應用程式");
  });

  it("uses cockpit setup and error boundary terminology", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["cockpitSetup.batch.activeCount"]).toBe("進行中 {count} 個");
    expect(pack["cockpitSetup.batch.peopleCount"]).toBe("{count, plural, one {# 個數位人} other {# 個數位人}}");
    expect(pack["cockpitSetup.pipeline.instrument"]).toBe("問卷");
    expect(pack["cockpitSetup.pipeline.nativeSut"]).toBe("原生 SUT");
    expect(pack["cockpitSetup.taskKind.example"]).toBe("範例");
    expect(pack["errorBoundary.description"]).toContain("Playground");
  });

  it("uses eval terminology without changing survey actor roles", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["eval.progress.batchAllFinished"]).toBe("{total, plural, one {全部 # 個數位人已完成} other {全部 # 個數位人已完成}}");
    expect(pack["eval.progress.batchFinished"]).toBe("已完成 {done}/{total, plural, one {# 個數位人} other {# 個數位人}}");
    expect(pack["eval.common.taskContextLabel"]).toBe("任務情境");
    expect(pack["eval.os.fullscreen.enter"]).toBe("進入全螢幕");
    expect(pack["eval.survey.answeredByPersona"]).toBe("數位人已回答");
    expect(pack["eval.survey.actor.scorer"]).toBe("評分器");
  });

  it("keeps exact eval context, result, and persona wording", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["eval.common.noSeparateContext"]).toBe("此任務沒有可用的獨立情境文件。");
    expect(pack["eval.os.progress.desktopAgent"]).toBe("桌面智慧體 · {count, plural, one {# 個步驟} other {# 個步驟}}");
    expect(pack["eval.survey.contextEmpty"]).toBe("本次執行沒有可用的獨立情境文件。");
    expect(pack["eval.survey.confidence"]).toBe("（信心度 {value}）");
    expect(pack["eval.errors.trialOutputArtifactsMissing"]).toBe("試驗已完成，但沒有儲存輸出。智慧體可能在送出結果前當機。");
    expect(pack["eval.web.personaFallback"]).toBe("數位人");
  });

  it("uses exact persona group, setup, and prompt wording", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["personaGroups.title"]).toBe("數位人群組");
    expect(pack["personaGroups.matchingFilters"]).toBe("有 <count>{count}</count> 個數位人符合篩選條件");
    expect(pack["personaSetup.filters.defaultPool"]).toBe("數位人池");
    expect(pack["personaSetup.filters.title"]).toBe("數位人篩選");
    expect(pack["personaSetup.strategy.selectedValues"]).toBe("{label} 的已選值");
    expect(pack["personaSetup.previewingCohortRef"]).toBe(" · 將透過群組參照啟動。");
    expect(pack["promptPanel.personaPrompt"]).toBe("數位人提示詞");
    expect(pack["personaSetup.errors.noPersonaFiles"]).toBe("此資料集沒有 persona YAML 檔案。");
  });

  it("uses exact reports wording and keeps report semantics", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["reports.analysis.aiSummary"]).toBe("各群組數位人說明的 AI 摘要");
    expect(pack["reports.analysis.examplesCount"]).toBe("範例（{count}）");
    expect(pack["reports.analysis.signalFrequency"]).toContain("樣本數：{count}");
    expect(pack["reports.bucket.grounding"]).toBe("無法基於 UI 提供依據");
    expect(pack["reports.context.personaAlignment"]).toBe("數位人符合度");
    expect(pack["reports.feedback.personaQuotes"]).toBe("{count, plural, one {# 則數位人引述，用於解釋該答案} other {# 則數位人引述，用於解釋該答案}}");
    expect(pack["reports.page.oneConversation"]).toBe("每個數位人各有一次對話 — 開啟任一項即可查看完整記錄");
    expect(pack["reports.pdf.batchReportTitle"]).toBe("數位人-任務 批次報告");
    expect(pack["reports.pdf.context"]).toBe("情境");
    expect(pack["reports.pdf.playground"]).toBe("Playground");
  });

  it("uses exact report table, task, and usage terminology", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["reports.report.allPersonasAgreed"]).toBe("{count} 個情境 · 所有數位人意見一致");
    expect(pack["reports.report.answer"]).toBe("答案");
    expect(pack["reports.report.breakDownByHint"]).toBe("本任務的篩選維與自訂維。");
    expect(pack["reports.report.resultFieldHint"]).toBe("選擇要放在欄上的測量結果。");
    expect(pack["reports.report.rowsFixedTo"]).toBe("列固定為 {label}。");
    expect(pack["reports.report.multiChoice"]).toBe("多選題");
    expect(pack["reports.report.multiSelect"]).toBe("多重選取 · 佔比可能超過 100%");
    expect(pack["reports.report.topPick"]).toBe("首選");
    expect(pack["reports.task.documentContext"]).toBe("情境");
    expect(pack["reports.task.agentModel"]).toBe("智慧體模型");
  });

  it("uses exact report summary counts and labels", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["reports.report.across"]).toBe("涵蓋 {areas}");
    expect(pack["reports.report.answeredCount"]).toBe("已回答：{count}");
    expect(pack["reports.report.clearCount"]).toBe("{count} 題趨勢明確");
    expect(pack["reports.report.missing"]).toBe("有 {count} 個試驗缺少產物");
    expect(pack["reports.report.missingCount"]).toBe("缺少 {count} 筆");
    expect(pack["reports.report.present"]).toBe("有值");
    expect(pack["reports.report.presentCount"]).toBe("{count} 筆有值");
    expect(pack["reports.report.splitCount"]).toBe("{count} 題意見分歧");
    expect(pack["reports.report.unanimousCount"]).toBe("{count} 題意見一致");
  });

  it("uses exact report strategy, task, and token labels", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();

    expect(pack["reports.strategy.audienceFilters"]).toBe("受眾篩選條件");
    expect(pack["reports.strategy.perCell"]).toBe("每個分層組合");
    expect(pack["reports.task.personasRun"]).toBe("執行數位人數");
    expect(pack["reports.task.personasRunTitle"]).toBe("本作業實際執行的不重複數位人數");
    expect(pack["reports.task.run"]).toBe("執行期間");
    expect(pack["reports.usage.tokenCache"]).toBe("{count} 個快取 Token");
  });

  it("uses exact theme, status, run-header, and optional-label wording", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const expected = {
      "reports.theme.dominantTwoWithSmaller": "在 {present} 個回答中，數量最多的兩個主題是「{primary}」（{primaryCount}）和「{secondary}」（{secondaryCount}），另有 {smallerAnswers} 個回答分布在 {smallerTopics, plural, one {# 個較少見的主題} other {# 個較少見的主題}}中。",
      "reports.theme.manyTopics": "在 {present} 個回答中，共形成 {topicCount} 個主要主題。最多的是「{primary}」（{primaryCount}），其次是「{secondary}」（{secondaryCount}）。",
      "reports.theme.manyTopicsRemaining": "其餘 {smallerAnswers} 個回答分布在 {smallerTopics, plural, one {# 個較少見的主題} other {# 個較少見的主題}}中。",
      "reports.status.completedCount": "已完成：{count}",
      "reports.status.completedWithFailures": "{completed}/{total}{failed, plural, =0 {} other { · # 個分析單元失敗}}{model}",
      "reports.status.summarizing": "正在彙整",
      "reports.status.toSummarize": "待彙整分析單元：{count}{model}",
      "reports.status.unitCount": "{count} 個分析單元{model}",
      "reports.status.waitingToSummarize": "等待彙整",
      "runHeader.subtitle.chatbot": "選擇數位人和聊天應用程式後啟動，逐條觀察模擬使用者的對話。",
      "runHeader.subtitle.osApp": "選擇數位人和 OS 應用程式任務後啟動。支援 Linux、macOS 或 iOS 上的原生應用程式。",
      "runHeader.subtitle.survey": "選擇一位數位人和問卷後啟動，觀察模擬使用者填寫表單，並由系統為回答評分。",
      "runHeader.subtitle.web": "選擇數位人和網頁任務後啟動，觀察模擬使用者在真實瀏覽器軌跡中完成網站操作。",
      "misc.optionalLabel": "選填標籤",
    } as const;

    expectMessages(pack, expected);
  });

  it("uses exact runs labels", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const expected = {
      "runs.answered": "已回答 {count} 題",
      "runs.appType": "應用程式類型",
      "runs.appType.chatbot": "聊天機器人",
      "runs.applicationTypeTooltip": "應用程式類型",
      "runs.browserTrace": "瀏覽器軌跡 · {count} 個步驟",
      "runs.checksPending": "檢查結果待定",
      "runs.desktopTrace": "桌面軌跡 · {count} 個步驟",
      "runs.status.agentRunning": "智慧體執行中",
      "runs.effort": "費力程度",
      "runs.evaluationDescription": "檢視任務完成情況、評估器檢查結果與數位人的自我報告。",
      "runs.eyebrow": "MatrAIx · 執行紀錄",
      "runs.filterByAppType": "依應用程式類型篩選",
      "runs.howSure": "信心程度：{percent}%",
      "runs.appType.osApp": "OS 應用程式",
      "runs.metPersonaNeed": "滿足數位人需求",
      "runs.noMeasurableSelfReportFields": "沒有記錄可量化的數位人自我報告欄位。",
      "runs.noPersonaSelfReport": "此試驗沒有記錄數位人自我報告（來源：<path>user_feedback.json</path>）。",
      "runs.osAppTask": "OS 應用程式任務",
      "runs.partially": "部分符合",
      "runs.personaProfile": "數位人個人檔案",
      "runs.personaSelfReport": "數位人自我報告",
      "runs.personaSelfReportDescription": "模擬數位人在任務後回報的內容。",
      "runs.questionTypes": "問題類型",
      "runs.questionsAnswered": "已回答題數",
      "runs.searchPlaceholder": "依作業名稱、應用程式類型或狀態搜尋…",
      "runs.started": "開始",
      "runs.taskContext": "任務情境",
      "runs.taskInstruction": "任務指示",
      "runs.taskOnSite": "在 {site} 上執行 {task}",
      "runs.title": "執行紀錄",
      "runs.trialCount": "{count} 次試驗",
      "runs.trialSummaryDescription": "結果、對話歷程與使用者回饋的簡要摘要。",
      "runs.trialsComplete": "{completed}/{total} 次試驗已完成",
    } as const;

    expectMessages(pack, expected);
  });

  it("uses exact shell, scorecard, exposure, and turn-bubble wording", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const expected = {
      "shell.home.personas": "數位人",
      "shell.nav.personaWorld": "數位人世界",
      "shell.preflight.blocksReady": "區塊已就緒",
      "scorecards.aria.overallRating": "整體評分 {overall} 分（滿分 {max} 分）",
      "scorecards.empty.failed": "此執行在評分前已停止。",
      "scorecards.rating.userRated": "使用者的評分",
      "scorecards.scale.legend": "應用程式表現良好時分數顯示<green>綠色</green>，表現普通時顯示<amber>琥珀色</amber>，未達標時顯示<red>紅色</red>。",
      "structuredExposure.details": "詳細資料",
      "turnBubble.emptyPersonaMessage": "（數位人未發言）",
      "turnBubble.persona": "數位人",
      "turnBubble.structuredWithoutReply": "應用程式回傳了結構化資料，但本輪未擷取到回覆文字。",
      "turnBubble.toolCallOk": "工具呼叫成功",
    } as const;

    expectMessages(pack, expected);
  });

  it("uses exact task-scorecard wording", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const expected = {
      "taskScorecard.os.accepted": "自動驗證器已接受桌面智慧體的輸出。",
      "taskScorecard.os.notAccepted": "驗證器未接受此輸出 · 請在中央面板檢查軌跡和產物。",
      "taskScorecard.os.outputArtifact": "輸出產物",
      "taskScorecard.survey.completion": "完成度",
      "taskScorecard.survey.completionInvalid": "已回答 {answered}/{total} 題 · 驗證時發現問題",
      "taskScorecard.survey.completionValid": "已回答 {answered}/{total} 題 · 回覆通過驗證",
      "taskScorecard.survey.finishedQuestionnaire": "數位人是否完成問卷？",
      "taskScorecard.survey.questionTypes": "問題類型",
      "taskScorecard.web.scaleLegend": "應用程式表現良好時分數顯示<green>綠色</green>，表現普通時顯示<amber>琥珀色</amber>，未達標時顯示<red>紅色</red>。",
    } as const;

    expectMessages(pack, expected);
  });

  it("uses exact task-setup wording", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const expected = {
      "taskSetup.details.document.context": "情境",
      "taskSetup.status.mcpNoToggle": "由 MCP 支援的任務；沒有可用的本地 HTTP 就緒切換開關。",
      "taskSetup.details.document.outputSchema": "輸出結構",
      "taskSetup.settings.osRuntime": "OS 執行環境",
      "taskSetup.settings.stopAfterTurns": "在指定的使用者輪次後停止。",
      "taskSetup.settings.turnLimit": "輪次上限",
      "taskSetup.settings.unlimitedTurns": "預設不限輪次，直到使用者模擬器決定結束。",
    } as const;

    expectMessages(pack, expected);
  });

  it("uses exact residual catalog and filter wording", async () => {
    const pack = await getLocaleDefinition("zh-Hant").load();
    const expected = {
      "catalog.personaCatalog.filterBySource": "依來源篩選",
      "catalog.personaCatalog.searchPlaceholder": "依角色、年齡或特徵搜尋（例如「經理」或「學生」）",
      "catalog.personaStore.filterByDataSource": "依資料來源篩選",
      "catalog.taskGallery.filter.osApp": "OS 應用程式",
      "catalog.taskGallery.filterByTaskType": "依任務類型篩選",
      "catalog.taskGallery.noTasksInType": "此類型暫無任務。請嘗試「全部」或其他篩選項。",
      "catalog.taskGallery.subtitle": "瀏覽 Playground 任務和實驗配方——搜尋、篩選，然後在 Playground 或 Experiments 中開啟。",
      "cockpit.environment.fixedFactsTitle": "這些執行環境資訊在本次執行期間固定不變。",
      "personaGroups.kind": "類型",
      "runs.filterByStatus": "依狀態篩選",
      "taskSetup.searchPlaceholder": "依名稱、描述或標籤篩選…",
    } as const;

    expectMessages(pack, expected);
  });

});
