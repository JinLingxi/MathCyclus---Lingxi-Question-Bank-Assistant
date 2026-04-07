import { AgentChatPanel } from "./AgentChatPanel";
import { useAgentContext } from "../contexts/AgentContext";
import { cn } from "../lib/utils";

export function AgentSidebar({ projectBound = false }: { projectBound?: boolean }) {
  const { sidebarOpen, setSidebarOpen } = useAgentContext();

  return (
    <div
      className={cn(
        "flex shrink-0 overflow-hidden border-l border-slate-200 bg-white transition-[width] duration-200 ease-out",
        // 收起时必须 min-w-0，否则内层 min-w-[22rem] 会顶住 flex 子项无法缩到 0，右侧出现白条
        sidebarOpen ? "w-[22rem]" : "w-0 min-w-0",
      )}
      aria-hidden={!sidebarOpen}
    >
      <div className="flex h-full w-full min-w-0 flex-col">
        <AgentChatPanel projectBound={projectBound} onRequestCollapse={() => setSidebarOpen(false)} />
      </div>
    </div>
  );
}
