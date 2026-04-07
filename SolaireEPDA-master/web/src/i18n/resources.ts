import commonZh from "./locales/zh/common.json";
import commonEn from "./locales/en/common.json";
import appZh from "./locales/zh/app.json";
import appEn from "./locales/en/app.json";
import composeZh from "./locales/zh/compose.json";
import composeEn from "./locales/en/compose.json";
import welcomeZh from "./locales/zh/welcome.json";
import welcomeEn from "./locales/en/welcome.json";
import settingsZh from "./locales/zh/settings.json";
import settingsEn from "./locales/en/settings.json";
import helpZh from "./locales/zh/help.json";
import helpEn from "./locales/en/help.json";
import bankZh from "./locales/zh/bank.json";
import bankEn from "./locales/en/bank.json";
import graphZh from "./locales/zh/graph.json";
import graphEn from "./locales/en/graph.json";
import templateZh from "./locales/zh/template.json";
import templateEn from "./locales/en/template.json";
import analysisZh from "./locales/zh/analysis.json";
import analysisEn from "./locales/en/analysis.json";
import logZh from "./locales/zh/log.json";
import logEn from "./locales/en/log.json";
import agentZh from "./locales/zh/agent.json";
import agentEn from "./locales/en/agent.json";
import componentsZh from "./locales/zh/components.json";
import componentsEn from "./locales/en/components.json";
import libZh from "./locales/zh/lib.json";
import libEn from "./locales/en/lib.json";

export const resources = {
  zh: {
    common: commonZh,
    app: appZh,
    compose: composeZh,
    welcome: welcomeZh,
    settings: settingsZh,
    help: helpZh,
    bank: bankZh,
    graph: graphZh,
    template: templateZh,
    analysis: analysisZh,
    log: logZh,
    agent: agentZh,
    components: componentsZh,
    lib: libZh,
  },
  en: {
    common: commonEn,
    app: appEn,
    compose: composeEn,
    welcome: welcomeEn,
    settings: settingsEn,
    help: helpEn,
    bank: bankEn,
    graph: graphEn,
    template: templateEn,
    analysis: analysisEn,
    log: logEn,
    agent: agentEn,
    components: componentsEn,
    lib: libEn,
  },
} as const;

export type AppLang = keyof typeof resources;
