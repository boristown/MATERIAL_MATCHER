# 数据盘候选与推荐（供两种安装向导 source 使用；纯本地探测，无网络访问）。
# disk_candidates：可读写、真实数据文件系统，按设备去重、剩余空间降序，最多 4 行；
# 每行格式：  剩余GB<TAB>挂载点<TAB>总GB
disk_candidates() {
  findmnt -rn -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null | while read -r target src fs opts; do
    case "$fs" in ext2|ext3|ext4|xfs|btrfs) ;; *) continue ;; esac
    [[ -d "$target" && ! -L "$target" ]] || continue
    case "$target" in /|/boot|/boot/*|/etc/*|/media/*|/run/*|/snap/*|/var/lib/docker/*|/var/lib/kubelet/*) ;; *) [[ "$target" == /* ]] || continue ;; esac
    grep -qw ro <<<"${opts//,/ }" && continue
    [[ -w "$target" ]] || continue
    stats=$(df -Pk "$target" 2>/dev/null | awk 'NR==2{print $2, $4}') || continue
    set -- $stats
    [[ -n "${2:-}" ]] || continue
    printf '%s\t%s\t%s\t%s\n' "$2" "$src" "$target" "$1"
  done | sort -nr | awk -F'\t' '!seen[$2]++ && ++n <= 4' | awk -F'\t' '{printf "%.1f\t%s\t%.1f\n", $1/1048576, $3, $4/1048576}'
}

# 渲染前三名屏幕文本
disk_candidates_text() {
  disk_candidates | awk -F'\t' 'NR<=3{printf "  %d) %s　　剩余 %.1f GB / 共 %.1f GB\n", NR, $2, $1, $3}'
}

disk_top_mount() { disk_candidates | head -1 | cut -f2; }

# 解析用户选择：输入 1..4 → 对应挂载点；输入含“/”的绝对路径 → 原样返回；空/其它 → 返回 1 表示取消语义由调用方处理
disk_resolve_choice() { # $1=原始输入；echo 结果；rc 0=成功 1=无效
  local answer="$1" list
  list="$(disk_candidates)"
  if [[ "$answer" =~ ^[1-4]$ ]]; then
    local mount
    mount="$(printf '%s\n' "$list" | awk -F'\t' -v n="$answer" 'NR==n{print $2}')"
    [[ -n "$mount" ]] && { printf '%s' "$mount"; return 0; } || return 1
  fi
  if [[ "$answer" == /* ]]; then
    [[ -d "$answer" || "$answer" == /*/* ]] && { printf '%s' "$answer"; return 0; }
  fi
  return 1
}
