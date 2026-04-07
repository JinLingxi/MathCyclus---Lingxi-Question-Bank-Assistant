/** True when a folder picker was cancelled or nothing was selected. */
export function pickFolderCanceledMessage(msg: string) {
  return (
    msg.includes("取消") ||
    msg.includes("未选择") ||
    /cancel(ed)?/i.test(msg) ||
    /user cancel/i.test(msg) ||
    /not select/i.test(msg)
  );
}
