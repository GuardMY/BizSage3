export const APP_TIME_ZONE = "Asia/Shanghai";

export function formatAppDateTime(
  value: string,
  options: Intl.DateTimeFormatOptions,
): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  return new Intl.DateTimeFormat("zh-CN", {
    ...options,
    timeZone: APP_TIME_ZONE,
  }).format(date);
}
