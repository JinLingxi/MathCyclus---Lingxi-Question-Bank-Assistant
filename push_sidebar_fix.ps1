$ErrorActionPreference = "Stop"

  function Invoke-Git {
      param(
          [string[]]$GitArgs,
          [string]$At = ""
      )

      if ($At) {
          & git -C $At @GitArgs
      } else {
          & git @GitArgs
      }

      if ($LASTEXITCODE -ne 0) {
          throw "Git command failed: git $($GitArgs -join ' ')"
      }
  }

  $worktree = ".push-main"

  if (Test-Path $worktree) {
      throw "$worktree already exists. Please remove or rename it first."
  }

  Invoke-Git @("fetch", "origin")
  Invoke-Git @("worktree", "add", "--detach", $worktree, "origin/main")

  try {
      $patch = @'
  diff --git a/question_bank_app.py b/question_bank_app.py
  --- a/question_bank_app.py
  +++ b/question_bank_app.py
  @@ -731,14 +731,19 @@
               function applySidebarState(isCollapsed) {{
                   sidebarCollapsed = isCollapsed;
  -                collapseButton.textContent = isCollapsed ? ">>" : "<<";
  -                collapseButton.title = isCollapsed ? "展开侧边栏" : "收缩侧边栏";
  -                collapseButton.setAttribute("aria-label", collapseButton.title);
  -                modeButton.dataset.sidebarCollapsed = isCollapsed ? "true" : "false";
  -                modeButton.setAttribute("aria-hidden", isCollapsed ? "true" : "false");
  -                modeButton.tabIndex = isCollapsed ? -1 : 0;
  +                const nextLabel = isCollapsed ? ">>" : "<<";
  +                const nextTitle = isCollapsed ? "展开侧边栏" : "收缩侧边栏";
  +                if (collapseButton.textContent !== nextLabel) collapseButton.textContent = nextLabel;
  +                if (collapseButton.title !== nextTitle) collapseButton.title = nextTitle;
  +                if (collapseButton.getAttribute("aria-label") !== nextTitle) collapseButton.setAttribute("aria-label", nextTitle);
  +                const nextCollapsed = isCollapsed ? "true" : "false";
  +                if (modeButton.dataset.sidebarCollapsed !== nextCollapsed) modeButton.dataset.sidebarCollapsed = nextCollapsed;
  +                const nextHidden = isCollapsed ? "true" : "false";
  +                if (modeButton.getAttribute("aria-hidden") !== nextHidden) modeButton.setAttribute("aria-hidden", nextHidden);
  +                const nextTabIndex = isCollapsed ? -1 : 0;
  +                if (modeButton.tabIndex !== nextTabIndex) modeButton.tabIndex = nextTabIndex;
                   if (!isCollapsed) {{
  -                    delete modeButton.dataset.switching;
  -                    modeButton.style.opacity = "";
  -                    modeButton.style.pointerEvents = "";
  +                    if (modeButton.dataset.switching) delete modeButton.dataset.switching;
  +                    if (modeButton.style.opacity) modeButton.style.opacity = "";
  +                    if (modeButton.style.pointerEvents) modeButton.style.pointerEvents = "";
                   }}
               }}
'@

      $patch = ($patch -split "`r?`n" | ForEach-Object {
          if ($_.StartsWith("  ")) { $_.Substring(2) } else { $_ }
      }) -join [Environment]::NewLine
      $patchPath = Join-Path $worktree "sidebar-fix.patch"
      Set-Content -LiteralPath $patchPath -Value $patch -Encoding utf8

      Invoke-Git @("apply", "sidebar-fix.patch") $worktree
      Remove-Item -LiteralPath $patchPath -Force

      Invoke-Git @("add", "--", "question_bank_app.py") $worktree
      Invoke-Git @("diff", "--cached", "--check") $worktree
      Invoke-Git @("commit", "-m", "fix: prevent sidebar observer DOM loop") $worktree
      Invoke-Git @("push", "origin", "HEAD:main") $worktree

      Write-Host ""
      Write-Host "修复已推送到 origin/main。" -ForegroundColor Green
  }
  finally {
      if (Test-Path $worktree) {
          git worktree remove --force $worktree
      }
  }
