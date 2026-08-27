import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_client.dart';
import '../design.dart';
import '../models.dart';

class APIKeysScreen extends StatefulWidget {
  const APIKeysScreen({super.key, required this.api});
  final APIClient api;
  @override
  State<APIKeysScreen> createState() => _APIKeysScreenState();
}

class _APIKeysScreenState extends State<APIKeysScreen> {
  List<APIKeyItem> items = [];
  bool loading = true;
  String error = '';

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final value = await widget.api.apiKeys();
      if (mounted)
        setState(() {
          items = value;
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
        'API 密钥',
        style: TextStyle(
          fontSize: 30,
          fontWeight: FontWeight.w700,
          letterSpacing: -1,
        ),
      ),
      actions: [
        CupertinoButton(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          onPressed: create,
          child: const Icon(CupertinoIcons.add_circled_solid, size: 27),
        ),
        const SizedBox(width: 4),
      ],
    ),
    body: loading && items.isEmpty
        ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
        : RefreshIndicator(
            onRefresh: load,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
              children: [
                _SecurityIntro(
                  active: items.where((item) => item.active).length,
                ),
                if (error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      error,
                      style: const TextStyle(color: AppColors.danger),
                    ),
                  ),
                const SectionLabel('访问密钥'),
                ...items.map(
                  (item) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _KeyCard(
                      item: item,
                      onRevoke: item.isMaster || !item.active
                          ? null
                          : () => revoke(item),
                    ),
                  ),
                ),
              ],
            ),
          ),
  );

  Future<void> create() async {
    final result =
        await showModalBottomSheet<
          ({String name, int rate, int daily, int concurrent})
        >(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => const _CreateKeySheet(),
        );
    if (result == null || !mounted) return;
    try {
      final created = await widget.api.createAPIKey(
        name: result.name,
        rate: result.rate,
        daily: result.daily,
        concurrent: result.concurrent,
      );
      await load();
      if (mounted) await _showSecret(created);
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _showSecret(CreatedAPIKey created) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (context) => Padding(
      padding: const EdgeInsets.fromLTRB(20, 2, 20, 30),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.key_rounded, size: 38, color: AppColors.accent),
          const SizedBox(height: 12),
          const Text(
            '密钥创建成功',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 7),
          const Text(
            '完整密钥只展示这一次，请立即复制给使用者。',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.muted),
          ),
          const SizedBox(height: 20),
          _CopyField(label: 'BASE URL', value: '${created.baseUrl}/v1'),
          _CopyField(label: 'MODEL', value: created.model),
          _CopyField(label: 'API KEY', value: created.key, secret: true),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: created.key));
              ScaffoldMessenger.of(
                context,
              ).showSnackBar(const SnackBar(content: Text('API Key 已复制')));
            },
            icon: const Icon(Icons.copy_rounded),
            label: const Text('复制 API Key'),
          ),
        ],
      ),
    ),
  );

  Future<void> revoke(APIKeyItem item) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('撤销这把密钥？'),
        content: Text('${item.name} 将立即无法继续调用接口。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('撤销'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.revokeAPIKey(item.id);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }
}

class _SecurityIntro extends StatelessWidget {
  const _SecurityIntro({required this.active});
  final int active;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: CupertinoColors.systemBackground,
      borderRadius: BorderRadius.circular(AppRadius.group),
    ),
    child: Row(
      children: [
        Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            color: AppColors.accentSoft,
            shape: BoxShape.circle,
          ),
          child: const Icon(
            CupertinoIcons.shield_fill,
            color: AppColors.accent,
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '$active 把密钥正在使用',
                style: const TextStyle(
                  color: AppColors.ink,
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                '建议每个使用者单独创建，额度与撤销互不影响。',
                style: TextStyle(
                  color: AppColors.muted,
                  fontSize: 12,
                  height: 1.4,
                ),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class _KeyCard extends StatelessWidget {
  const _KeyCard({required this.item, this.onRevoke});
  final APIKeyItem item;
  final VoidCallback? onRevoke;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: item.isMaster ? AppColors.soft : AppColors.accentSoft,
                  borderRadius: BorderRadius.circular(AppRadius.control),
                ),
                child: Icon(
                  item.isMaster
                      ? Icons.admin_panel_settings_outlined
                      : Icons.key_rounded,
                  color: item.isMaster ? AppColors.ink : AppColors.accent,
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
                      item.keyHint,
                      style: const TextStyle(
                        fontFamily: 'monospace',
                        color: AppColors.muted,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: item.active ? AppColors.accentSoft : AppColors.soft,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  item.active ? '可用' : '已停用',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    color: item.active ? AppColors.accent : AppColors.muted,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              _Metric(
                label: '本分钟',
                value: item.isMaster
                    ? '不限'
                    : '${item.usageMinute}/${item.rateLimit}',
              ),
              _Metric(
                label: '今天',
                value: item.isMaster
                    ? '不统计'
                    : '${item.usageToday}/${item.dailyLimit}',
              ),
              _Metric(
                label: '等待中',
                value: item.isMaster
                    ? '不限'
                    : '${item.pending}/${item.concurrentLimit}',
              ),
            ],
          ),
          if (onRevoke != null) ...[
            const Divider(height: 25),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: onRevoke,
                icon: const Icon(Icons.block_rounded, size: 17),
                label: const Text('撤销密钥'),
                style: TextButton.styleFrom(foregroundColor: AppColors.danger),
              ),
            ),
          ],
        ],
      ),
    ),
  );
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label, value;
  @override
  Widget build(BuildContext context) => Expanded(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(fontSize: 10, color: AppColors.muted),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
        ),
      ],
    ),
  );
}

class _CreateKeySheet extends StatefulWidget {
  const _CreateKeySheet();
  @override
  State<_CreateKeySheet> createState() => _CreateKeySheetState();
}

class _CreateKeySheetState extends State<_CreateKeySheet> {
  final name = TextEditingController(text: '移动端创建'),
      rate = TextEditingController(text: '10'),
      daily = TextEditingController(text: '100'),
      concurrent = TextEditingController(text: '3');
  @override
  void dispose() {
    name.dispose();
    rate.dispose();
    daily.dispose();
    concurrent.dispose();
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
        const Text(
          '创建 API Key',
          style: TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 6),
        const Text(
          '给这把密钥起一个容易识别的名字，并设置独立额度。',
          style: TextStyle(color: AppColors.muted),
        ),
        const SizedBox(height: 20),
        TextField(
          controller: name,
          autofocus: true,
          decoration: const InputDecoration(labelText: '备注名称'),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: rate,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: '每分钟'),
              ),
            ),
            const SizedBox(width: 9),
            Expanded(
              child: TextField(
                controller: daily,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: '每天'),
              ),
            ),
            const SizedBox(width: 9),
            Expanded(
              child: TextField(
                controller: concurrent,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: '同时等待'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 18),
        FilledButton(
          onPressed: () {
            if (name.text.trim().isEmpty) return;
            Navigator.pop(context, (
              name: name.text.trim(),
              rate: int.tryParse(rate.text) ?? 10,
              daily: int.tryParse(daily.text) ?? 100,
              concurrent: int.tryParse(concurrent.text) ?? 3,
            ));
          },
          child: const Text('创建并查看密钥'),
        ),
      ],
    ),
  );
}

class _CopyField extends StatelessWidget {
  const _CopyField({
    required this.label,
    required this.value,
    this.secret = false,
  });
  final String label, value;
  final bool secret;
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 9),
    padding: const EdgeInsets.fromLTRB(13, 10, 6, 10),
    decoration: BoxDecoration(
      color: AppColors.soft,
      borderRadius: BorderRadius.circular(AppRadius.control),
    ),
    child: Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: const TextStyle(
                  fontSize: 9,
                  color: AppColors.muted,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                value,
                maxLines: secret ? 3 : 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
              ),
            ],
          ),
        ),
        IconButton(
          onPressed: () => Clipboard.setData(ClipboardData(text: value)),
          icon: const Icon(Icons.copy_rounded, size: 18),
        ),
      ],
    ),
  );
}
