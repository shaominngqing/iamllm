part of 'conversation_screen.dart';

class _ViewBanner extends StatelessWidget {
  const _ViewBanner({required this.tab, required this.onClose});
  final String tab;
  final VoidCallback onClose;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
    color: AppColors.accentSoft,
    child: Row(
      children: [
        Icon(
          tab == 'run'
              ? Icons.monitor_heart_outlined
              : Icons.data_object_rounded,
          size: 18,
          color: AppColors.accent,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            tab == 'run' ? '正在查看运行记录' : '正在查看未经整理的原始上下文',
            style: const TextStyle(fontSize: 12),
          ),
        ),
        TextButton(onPressed: onClose, child: const Text('回到聊天')),
      ],
    ),
  );
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.current,
    required this.controller,
    required this.busy,
    required this.sendState,
    required this.quickReplies,
    required this.onSend,
    required this.onFinish,
    required this.onDirect,
    required this.onTool,
    required this.onRetry,
  });
  final HumanRequest current;
  final TextEditingController controller;
  final bool busy;
  final String sendState;
  final List<QuickReply> quickReplies;
  final VoidCallback onSend, onFinish, onDirect, onTool, onRetry;

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: AppColors.line)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              StatusDot(active: current.clientOnline, size: 7),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  current.clientOnline ? '客户端在线，回复会实时抵达' : '客户端离线，回复会安全保存',
                  style: const TextStyle(fontSize: 11, color: AppColors.muted),
                ),
              ),
              if (current.streamChunkCount > 0)
                TextButton.icon(
                  onPressed: busy ? null : onFinish,
                  icon: const Icon(CupertinoIcons.check_mark, size: 17),
                  label: const Text('完成'),
                ),
            ],
          ),
          if (quickReplies.isNotEmpty)
            SizedBox(
              height: 38,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: quickReplies.length,
                separatorBuilder: (_, __) => const SizedBox(width: 7),
                itemBuilder: (_, index) => ActionChip(
                  label: Text(quickReplies[index].title),
                  onPressed: () =>
                      controller.text = quickReplies[index].content,
                ),
              ),
            ),
          Container(
            margin: const EdgeInsets.only(top: 7),
            padding: const EdgeInsets.fromLTRB(4, 2, 5, 2),
            decoration: BoxDecoration(
              color: Colors.white,
              border: Border.all(color: const Color(0xffd7d7d9)),
              borderRadius: BorderRadius.circular(24),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x10000000),
                  blurRadius: 12,
                  offset: Offset(0, 4),
                ),
              ],
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                IconButton(
                  tooltip: '更多回答方式',
                  onPressed: current.streamChunkCount > 0
                      ? null
                      : () => _showActions(context),
                  icon: const Icon(CupertinoIcons.add_circled),
                ),
                Expanded(
                  child: TextField(
                    controller: controller,
                    minLines: 1,
                    maxLines: 5,
                    keyboardType: TextInputType.multiline,
                    decoration: const InputDecoration(
                      hintText: '给用户回复消息',
                      filled: false,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      contentPadding: EdgeInsets.symmetric(vertical: 13),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: IconButton.filled(
                    tooltip: '发送一段',
                    onPressed: busy ? null : onSend,
                    style: IconButton.styleFrom(
                      backgroundColor: AppColors.accent,
                      foregroundColor: Colors.white,
                      disabledBackgroundColor: const Color(0xffd5d5d7),
                    ),
                    icon: busy
                        ? const SizedBox(
                            width: 17,
                            height: 17,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(CupertinoIcons.arrow_up),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 5),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (sendState == 'sending')
                const Text(
                  '正在发送…',
                  style: TextStyle(
                    fontSize: 10,
                    color: CupertinoColors.secondaryLabel,
                  ),
                )
              else if (sendState == 'failed') ...[
                const Icon(
                  CupertinoIcons.exclamationmark_circle,
                  size: 13,
                  color: CupertinoColors.systemRed,
                ),
                const SizedBox(width: 4),
                const Text(
                  '发送失败',
                  style: TextStyle(
                    fontSize: 10,
                    color: CupertinoColors.systemRed,
                  ),
                ),
                CupertinoButton(
                  padding: const EdgeInsets.symmetric(horizontal: 5),
                  minimumSize: const Size(0, 24),
                  onPressed: busy ? null : onRetry,
                  child: const Text(
                    '重试',
                    style: TextStyle(fontSize: 10, fontWeight: FontWeight.w600),
                  ),
                ),
              ] else if (sendState == 'sent')
                const Text(
                  '✓ 已送达',
                  style: TextStyle(
                    fontSize: 10,
                    color: CupertinoColors.systemGreen,
                  ),
                )
              else
                Text(
                  current.streamChunkCount > 0
                      ? '继续发送会追加到同一条回复，点“完成”结束'
                      : '发送后立即流式抵达；也可以从 + 选择整段回答',
                  style: const TextStyle(fontSize: 9, color: Color(0xff9b9b9e)),
                ),
            ],
          ),
        ],
      ),
    ),
  );

  void _showActions(BuildContext context) {
    showCupertinoModalPopup<void>(
      context: context,
      builder: (context) => CupertinoActionSheet(
        title: const Text('回答方式'),
        actions: [
          CupertinoActionSheetAction(
            onPressed: () {
              Navigator.pop(context);
              onDirect();
            },
            child: const Text('整段发送并结束'),
          ),
          if (current.tools.isNotEmpty)
            CupertinoActionSheetAction(
              onPressed: () {
                Navigator.pop(context);
                onTool();
              },
              child: const Text('调用客户端工具'),
            ),
        ],
        cancelButton: CupertinoActionSheetAction(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({
    required this.message,
    required this.api,
    this.streamState = '',
  });
  final ChatMessage message;
  final APIClient api;
  final String streamState;

  @override
  Widget build(BuildContext context) {
    final user = message.role == 'user';
    if (user) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.sizeOf(context).width * .78,
          ),
          margin: const EdgeInsets.only(left: 48, bottom: 22),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
          decoration: BoxDecoration(
            color: AppColors.soft,
            borderRadius: BorderRadius.circular(AppRadius.bubble),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: _content(message.content),
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(right: 8, bottom: 24),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const BrandAvatar(size: 30),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (streamState.isNotEmpty) ...[
                  Text(
                    streamState == 'sending'
                        ? '正在发送'
                        : streamState == 'failed'
                        ? '发送失败'
                        : '已送达',
                    style: TextStyle(
                      fontSize: 10,
                      color: streamState == 'failed'
                          ? CupertinoColors.systemRed
                          : streamState == 'sent'
                          ? CupertinoColors.systemGreen
                          : AppColors.accent,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 5),
                ],
                ..._content(message.content),
              ],
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _content(dynamic content) {
    if (content is String)
      return [
        SelectableText(
          content,
          style: const TextStyle(fontSize: 15, height: 1.62),
        ),
      ];
    if (content is List) {
      return content.whereType<Map>().map((raw) {
        final part = raw.cast<String, dynamic>();
        if ('${part['type']}'.contains('text'))
          return SelectableText(
            '${part['text'] ?? ''}',
            style: const TextStyle(fontSize: 15, height: 1.62),
          );
        if ('${part['type']}'.contains('image')) {
          dynamic value = part['image_url'];
          if (value is Map) value = value['url'];
          if (value is String && value.startsWith('data:')) {
            try {
              return ClipRRect(
                borderRadius: BorderRadius.circular(AppRadius.control),
                child: Image.memory(
                  Uint8List.fromList(base64Decode(value.split(',').last)),
                ),
              );
            } catch (_) {}
          }
          if (value is String) {
            return ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.control),
              child: Image.network(
                value.startsWith('/') ? api.uri(value).toString() : value,
                headers: value.startsWith('/admin/')
                    ? {'Authorization': 'Bearer ${api.session.accessToken}'}
                    : null,
              ),
            );
          }
        }
        return Container(
          margin: const EdgeInsets.only(top: 8),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppColors.soft,
            borderRadius: BorderRadius.circular(AppRadius.control),
          ),
          child: Row(
            children: [
              const Icon(Icons.attach_file_rounded, size: 18),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  '${part['file']?['filename'] ?? part['type'] ?? '附件'}',
                ),
              ),
            ],
          ),
        );
      }).toList();
    }
    return [Text('$content')];
  }
}

class _Run extends StatelessWidget {
  const _Run({required this.item});
  final HumanRequest item;
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      _row(Icons.hub_outlined, '协议来源', sourceName(item.source)),
      _row(Icons.memory_rounded, '模型', item.model),
      _row(Icons.data_usage_rounded, '上下文', '${item.contextChars} 字符'),
      _row(Icons.extension_outlined, '工具定义', '${item.toolCount} 项'),
      _row(
        Icons.stream_rounded,
        '回复传输',
        item.streamChunkCount > 0
            ? '${item.streamChunkCount} 个 chunk，聊天中合为一条'
            : '整段返回',
      ),
      if (item.chunks.isNotEmpty)
        Card(
          child: ExpansionTile(
            title: const Text('查看 chunk 明细'),
            children: item.chunks
                .map(
                  (chunk) => ListTile(
                    dense: true,
                    leading: Text(
                      '#${chunk.position}',
                      style: const TextStyle(color: AppColors.muted),
                    ),
                    title: Text(chunk.content),
                  ),
                )
                .toList(),
          ),
        ),
      const SectionLabel('客户端工具'),
      ...item.tools.asMap().entries.map(
        (entry) => Card(
          child: ExpansionTile(
            title: Text('工具 ${entry.key + 1}'),
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: SelectableText(
                  const JsonEncoder.withIndent('  ').convert(entry.value),
                ),
              ),
            ],
          ),
        ),
      ),
    ],
  );

  Widget _row(IconData icon, String title, String value) => Padding(
    padding: const EdgeInsets.only(bottom: 9),
    child: Card(
      child: ListTile(
        leading: Icon(icon, size: 21),
        title: Text(title),
        trailing: SizedBox(
          width: 150,
          child: Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.end,
            style: const TextStyle(color: AppColors.muted),
          ),
        ),
      ),
    ),
  );
}
