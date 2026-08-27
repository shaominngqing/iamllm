import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import '../api_client.dart';
import '../design.dart';
import '../models.dart';

class AutomationScreen extends StatefulWidget {
  const AutomationScreen({super.key, required this.api});
  final APIClient api;
  @override
  State<AutomationScreen> createState() => _AutomationScreenState();
}

class _AutomationScreenState extends State<AutomationScreen> {
  List<AutoReplyRule> rules = [];
  List<QuickReply> replies = [];
  bool loading = true;
  int tab = 0;
  String error = '';

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final values = await Future.wait([
        widget.api.autoRules(),
        widget.api.quickReplies(all: true),
      ]);
      if (mounted)
        setState(() {
          rules = values[0] as List<AutoReplyRule>;
          replies = values[1] as List<QuickReply>;
          error = '';
        });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      centerTitle: false,
      toolbarHeight: 64,
      title: const Text(
        '自动回复',
        style: TextStyle(
          fontSize: 30,
          fontWeight: FontWeight.w700,
          letterSpacing: -1,
        ),
      ),
      actions: [
        CupertinoButton(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          onPressed: tab == 0 ? () => editRule() : () => editReply(),
          child: const Icon(CupertinoIcons.add_circled_solid, size: 27),
        ),
        const SizedBox(width: 4),
      ],
    ),
    body: Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 6, 16, 12),
          child: SizedBox(
            width: double.infinity,
            child: CupertinoSlidingSegmentedControl<int>(
              groupValue: tab,
              thumbColor: CupertinoColors.systemBackground,
              backgroundColor: CupertinoColors.systemGrey5,
              children: {
                0: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 7),
                  child: Text(
                    '自动规则  ${rules.where((item) => item.active).length}',
                  ),
                ),
                1: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 7),
                  child: Text(
                    '快捷话术  ${replies.where((item) => item.active).length}',
                  ),
                ),
              },
              onValueChanged: (value) {
                if (value != null) setState(() => tab = value);
              },
            ),
          ),
        ),
        if (error.isNotEmpty)
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(error, style: const TextStyle(color: AppColors.danger)),
          ),
        Expanded(
          child: loading
              ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
              : RefreshIndicator(
                  onRefresh: load,
                  child: tab == 0 ? _rulesList() : _repliesList(),
                ),
        ),
      ],
    ),
  );

  Widget _rulesList() => rules.isEmpty
      ? const EmptyState(
          icon: Icons.bolt_outlined,
          title: '还没有自动规则',
          subtitle: '创建关键词或时间段规则，让服务在你没空时先接住场面。',
        )
      : ListView.builder(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 28),
          itemCount: rules.length + 1,
          itemBuilder: (context, index) {
            if (index == 0) return const _AutomationIntro();
            final item = rules[index - 1];
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                child: InkWell(
                  borderRadius: BorderRadius.circular(AppRadius.group),
                  onTap: () => editRule(item),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 14, 10, 14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              width: 38,
                              height: 38,
                              decoration: BoxDecoration(
                                color: item.ruleType == 'schedule'
                                    ? const Color(0xfffff3dd)
                                    : AppColors.accentSoft,
                                borderRadius: BorderRadius.circular(
                                  AppRadius.control,
                                ),
                              ),
                              child: Icon(
                                item.ruleType == 'schedule'
                                    ? Icons.schedule_rounded
                                    : Icons.tag_rounded,
                                color: item.ruleType == 'schedule'
                                    ? const Color(0xffb97818)
                                    : AppColors.accent,
                                size: 20,
                              ),
                            ),
                            const SizedBox(width: 11),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    item.name,
                                    style: const TextStyle(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                  const SizedBox(height: 3),
                                  Text(
                                    _ruleCondition(item),
                                    style: const TextStyle(
                                      fontSize: 11,
                                      color: AppColors.muted,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Switch.adaptive(
                              value: item.active,
                              onChanged: (value) => toggleRule(item, value),
                            ),
                            IconButton(
                              tooltip: '删除规则',
                              visualDensity: VisualDensity.compact,
                              onPressed: () => deleteRule(item),
                              icon: const Icon(
                                Icons.delete_outline_rounded,
                                size: 20,
                                color: AppColors.muted,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: AppColors.soft,
                            borderRadius: BorderRadius.circular(
                              AppRadius.control,
                            ),
                          ),
                          child: Text(
                            item.responseText,
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 13, height: 1.5),
                          ),
                        ),
                        if (item.delaySeconds > 0)
                          Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Text(
                              '等待 ${item.delaySeconds} 秒后发送',
                              style: const TextStyle(
                                fontSize: 10,
                                color: AppColors.muted,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        );

  Widget _repliesList() => replies.isEmpty
      ? const EmptyState(
          icon: Icons.short_text_rounded,
          title: '还没有快捷话术',
          subtitle: '保存高频回答，在回复用户时一点就能填入。',
        )
      : ListView.separated(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 28),
          itemCount: replies.length,
          separatorBuilder: (_, __) => const SizedBox(height: 10),
          itemBuilder: (context, index) {
            final item = replies[index];
            return Card(
              child: InkWell(
                borderRadius: BorderRadius.circular(AppRadius.group),
                onTap: () => editReply(item),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: 38,
                        height: 38,
                        decoration: BoxDecoration(
                          color: AppColors.soft,
                          borderRadius: BorderRadius.circular(
                            AppRadius.control,
                          ),
                        ),
                        child: const Icon(Icons.format_quote_rounded, size: 20),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    item.title,
                                    style: const TextStyle(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 7,
                                    vertical: 3,
                                  ),
                                  decoration: BoxDecoration(
                                    color: item.active
                                        ? AppColors.accentSoft
                                        : AppColors.soft,
                                    borderRadius: BorderRadius.circular(20),
                                  ),
                                  child: Text(
                                    item.active ? '使用中' : '已停用',
                                    style: TextStyle(
                                      fontSize: 9,
                                      color: item.active
                                          ? AppColors.accent
                                          : AppColors.muted,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 7),
                            Text(
                              item.content,
                              maxLines: 3,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                color: AppColors.muted,
                                height: 1.5,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 6),
                      IconButton(
                        tooltip: '删除话术',
                        visualDensity: VisualDensity.compact,
                        onPressed: () => deleteReply(item),
                        icon: const Icon(
                          Icons.delete_outline_rounded,
                          size: 20,
                          color: AppColors.muted,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );

  Future<void> toggleRule(AutoReplyRule item, bool active) async {
    try {
      await widget.api.saveAutoRule(item.copyWith(active: active));
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> editRule([AutoReplyRule? existing]) async {
    final value = await showModalBottomSheet<AutoReplyRule>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _RuleSheet(item: existing),
    );
    if (value == null) return;
    try {
      await widget.api.saveAutoRule(value);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> editReply([QuickReply? existing]) async {
    final value = await showModalBottomSheet<QuickReply>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _ReplySheet(item: existing),
    );
    if (value == null) return;
    try {
      await widget.api.saveQuickReply(value);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<bool> confirmDelete(String name) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('确认删除？'),
          content: Text('“$name”删除后无法恢复。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('删除'),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> deleteRule(AutoReplyRule item) async {
    if (!await confirmDelete(item.name)) return;
    try {
      await widget.api.deleteAutoRule(item.id);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> deleteReply(QuickReply item) async {
    if (!await confirmDelete(item.title)) return;
    try {
      await widget.api.deleteQuickReply(item.id);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

String _ruleCondition(AutoReplyRule item) => item.ruleType == 'schedule'
    ? '${item.startTime}—${item.endTime}'
    : '${item.matchType == 'exact' ? '完全等于' : '包含'}「${item.pattern}」';

class _AutomationIntro extends StatelessWidget {
  const _AutomationIntro();
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: AppSpacing.md),
    padding: const EdgeInsets.all(AppSpacing.md),
    decoration: BoxDecoration(
      color: AppColors.accentSoft,
      borderRadius: BorderRadius.circular(AppRadius.group),
    ),
    child: const Row(
      children: [
        Icon(Icons.auto_awesome_rounded, color: AppColors.accent),
        SizedBox(width: 12),
        Expanded(
          child: Text(
            '命中规则后会直接流式返回，不会在人工待回答队列里闪一下。',
            style: TextStyle(fontSize: 12, height: 1.45),
          ),
        ),
      ],
    ),
  );
}

class _RuleSheet extends StatefulWidget {
  const _RuleSheet({this.item});
  final AutoReplyRule? item;
  @override
  State<_RuleSheet> createState() => _RuleSheetState();
}

class _RuleSheetState extends State<_RuleSheet> {
  late final TextEditingController name, pattern, response, delay, start, end;
  late String type, match;
  bool active = true;
  @override
  void initState() {
    super.initState();
    final item = widget.item;
    name = TextEditingController(text: item?.name ?? '忙碌时先接住');
    pattern = TextEditingController(text: item?.pattern ?? '在吗');
    response = TextEditingController(text: item?.responseText ?? '在的，脑子正在开机。');
    delay = TextEditingController(text: '${item?.delaySeconds ?? 0}');
    start = TextEditingController(
      text: item?.startTime.isNotEmpty == true ? item!.startTime : '10:00',
    );
    end = TextEditingController(
      text: item?.endTime.isNotEmpty == true ? item!.endTime : '19:00',
    );
    type = item?.ruleType ?? 'keyword';
    match = item?.matchType ?? 'contains';
    active = item?.active ?? true;
  }

  @override
  void dispose() {
    name.dispose();
    pattern.dispose();
    response.dispose();
    delay.dispose();
    start.dispose();
    end.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    padding: EdgeInsets.fromLTRB(
      20,
      4,
      20,
      MediaQuery.viewInsetsOf(context).bottom + 26,
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          widget.item == null ? '新建自动规则' : '编辑自动规则',
          style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 18),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'keyword', label: Text('关键词')),
            ButtonSegment(value: 'schedule', label: Text('时间段')),
          ],
          selected: {type},
          showSelectedIcon: false,
          onSelectionChanged: (value) => setState(() => type = value.first),
        ),
        const SizedBox(height: 14),
        TextField(
          controller: name,
          decoration: const InputDecoration(labelText: '规则名称'),
        ),
        const SizedBox(height: 11),
        if (type == 'keyword') ...[
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: match,
                  items: const [
                    DropdownMenuItem(value: 'contains', child: Text('包含')),
                    DropdownMenuItem(value: 'exact', child: Text('完全等于')),
                  ],
                  onChanged: (value) => setState(() => match = value ?? match),
                  decoration: const InputDecoration(labelText: '匹配方式'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                flex: 2,
                child: TextField(
                  controller: pattern,
                  decoration: const InputDecoration(labelText: '关键词'),
                ),
              ),
            ],
          ),
        ] else ...[
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: start,
                  decoration: const InputDecoration(labelText: '开始时间'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: TextField(
                  controller: end,
                  decoration: const InputDecoration(labelText: '结束时间'),
                ),
              ),
            ],
          ),
        ],
        const SizedBox(height: 11),
        TextField(
          controller: response,
          minLines: 3,
          maxLines: 6,
          decoration: const InputDecoration(labelText: '自动回复内容'),
        ),
        const SizedBox(height: 11),
        TextField(
          controller: delay,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(
            labelText: '延迟秒数',
            helperText: '0—300 秒',
          ),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('创建后立即启用'),
          value: active,
          onChanged: (value) => setState(() => active = value),
        ),
        const SizedBox(height: 8),
        FilledButton(onPressed: save, child: const Text('保存规则')),
      ],
    ),
  );
  void save() {
    if (name.text.trim().isEmpty ||
        response.text.trim().isEmpty ||
        (type == 'keyword' && pattern.text.trim().isEmpty))
      return;
    Navigator.pop(
      context,
      AutoReplyRule(
        id: widget.item?.id ?? '',
        name: name.text.trim(),
        ruleType: type,
        matchType: match,
        pattern: type == 'keyword' ? pattern.text.trim() : '',
        responseText: response.text.trim(),
        startTime: type == 'schedule' ? start.text.trim() : '',
        endTime: type == 'schedule' ? end.text.trim() : '',
        days: widget.item?.days ?? const [0, 1, 2, 3, 4, 5, 6],
        delaySeconds: int.tryParse(delay.text) ?? 0,
        priority: widget.item?.priority ?? 0,
        active: active,
      ),
    );
  }
}

class _ReplySheet extends StatefulWidget {
  const _ReplySheet({this.item});
  final QuickReply? item;
  @override
  State<_ReplySheet> createState() => _ReplySheetState();
}

class _ReplySheetState extends State<_ReplySheet> {
  late final TextEditingController title, content, category;
  bool active = true;
  @override
  void initState() {
    super.initState();
    final item = widget.item;
    title = TextEditingController(text: item?.title ?? '收到');
    content = TextEditingController(text: item?.content ?? '收到，我先看一下。');
    category = TextEditingController(text: item?.category ?? '常用');
    active = item?.active ?? true;
  }

  @override
  void dispose() {
    title.dispose();
    content.dispose();
    category.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.fromLTRB(
      20,
      4,
      20,
      MediaQuery.viewInsetsOf(context).bottom + 26,
    ),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          widget.item == null ? '新建快捷话术' : '编辑快捷话术',
          style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 18),
        Row(
          children: [
            Expanded(
              flex: 2,
              child: TextField(
                controller: title,
                decoration: const InputDecoration(labelText: '按钮名称'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: TextField(
                controller: category,
                decoration: const InputDecoration(labelText: '分类'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 11),
        TextField(
          controller: content,
          minLines: 3,
          maxLines: 6,
          decoration: const InputDecoration(labelText: '回复内容'),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('在会话中显示'),
          value: active,
          onChanged: (value) => setState(() => active = value),
        ),
        FilledButton(
          onPressed: () {
            if (title.text.trim().isEmpty || content.text.trim().isEmpty)
              return;
            Navigator.pop(
              context,
              QuickReply(
                id: widget.item?.id ?? '',
                title: title.text.trim(),
                content: content.text.trim(),
                category: category.text.trim(),
                active: active,
              ),
            );
          },
          child: const Text('保存话术'),
        ),
      ],
    ),
  );
}
