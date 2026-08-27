import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_client.dart';
import '../app_info.dart';
import '../design.dart';
import '../models.dart';

class ServiceScreen extends StatefulWidget {
  const ServiceScreen({super.key, required this.api, required this.onLogout});
  final APIClient api;
  final Future<void> Function() onLogout;
  @override
  State<ServiceScreen> createState() => _ServiceScreenState();
}

class _ServiceScreenState extends State<ServiceScreen> {
  ServiceOverview? overview;
  ModelProfile? profile;
  List<Device> devices = [];
  String currentDeviceId = '', error = '';
  bool loading = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final values = await Future.wait([
        widget.api.overview(),
        widget.api.profile(),
        widget.api.devices(),
      ]);
      final deviceData =
          values[2] as ({List<Device> items, String currentDeviceId});
      if (mounted)
        setState(() {
          overview = values[0] as ServiceOverview;
          profile = values[1] as ModelProfile;
          devices = deviceData.items;
          currentDeviceId = deviceData.currentDeviceId;
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
        '服务',
        style: TextStyle(
          fontSize: 30,
          fontWeight: FontWeight.w700,
          letterSpacing: -1,
        ),
      ),
      actions: [
        CupertinoButton(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          onPressed: load,
          child: const Icon(CupertinoIcons.refresh, size: 21),
        ),
        const SizedBox(width: 4),
      ],
    ),
    body: loading && overview == null
        ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
        : RefreshIndicator(
            onRefresh: load,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 34),
              children: [
                if (error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      error,
                      style: const TextStyle(color: AppColors.danger),
                    ),
                  ),
                if (overview != null) _ServiceCard(data: overview!),
                const SectionLabel('公开资料'),
                if (profile != null)
                  _ProfileCard(profile: profile!, onEdit: editProfile),
                SectionLabel(
                  '登录设备',
                  trailing: Text(
                    '${devices.where((item) => item.active).length} 台可用',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.muted,
                    ),
                  ),
                ),
                ...devices.map(
                  (device) => Padding(
                    padding: const EdgeInsets.only(bottom: 9),
                    child: _DeviceCard(
                      device: device,
                      current: device.id == currentDeviceId,
                      onTap: () => showDevice(device),
                    ),
                  ),
                ),
                const SectionLabel('当前应用'),
                Card(
                  child: Column(
                    children: [
                      ListTile(
                        leading: const Icon(Icons.dns_outlined),
                        title: const Text('服务器'),
                        subtitle: Text(widget.api.session.baseUrl),
                        trailing: const Icon(
                          CupertinoIcons.chevron_forward,
                          size: 16,
                          color: CupertinoColors.tertiaryLabel,
                        ),
                      ),
                      const Divider(height: 1, indent: 56),
                      const ListTile(
                        leading: Icon(Icons.info_outline_rounded),
                        title: Text('移动控制台'),
                        trailing: Text(
                          appVersionLabel,
                          style: TextStyle(color: AppColors.muted),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
                OutlinedButton.icon(
                  onPressed: logout,
                  icon: const Icon(Icons.logout_rounded),
                  label: const Text('退出这台设备'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.danger,
                  ),
                ),
              ],
            ),
          ),
  );

  Future<void> editProfile() async {
    final existing = profile;
    if (existing == null) return;
    final value = await showModalBottomSheet<ModelProfile>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _ProfileSheet(profile: existing),
    );
    if (value == null) return;
    try {
      final saved = await widget.api.saveProfile(value);
      if (mounted) setState(() => profile = saved);
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('退出这台设备？'),
        content: const Text('退出后需要重新输入配对码或管理员密码。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('退出'),
          ),
        ],
      ),
    );
    if (ok == true) await widget.onLogout();
  }

  Future<void> showDevice(Device device) async {
    final current = device.id == currentDeviceId;
    final revoke = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    device.name,
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                StatusDot(active: device.active),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              current
                  ? '当前正在使用的管理设备'
                  : '上次使用 ${relativeTime(device.lastSeenAt)}',
              style: const TextStyle(color: AppColors.muted),
            ),
            const SizedBox(height: 18),
            _DeviceFact(label: '设备型号', value: device.model),
            _DeviceFact(label: '系统', value: device.osVersion),
            _DeviceFact(label: '应用版本', value: device.appVersion),
            _DeviceFact(
              label: '地区 / 时区',
              value: '${device.locale} · ${device.timezone}',
            ),
            _DeviceFact(label: '最近 IP', value: device.ipAddress),
            if (!current && device.active) ...[
              const SizedBox(height: 18),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.danger,
                ),
                onPressed: () => Navigator.pop(context, true),
                icon: const Icon(Icons.link_off_rounded),
                label: const Text('撤销这台设备'),
              ),
            ],
          ],
        ),
      ),
    );
    if (revoke != true) return;
    try {
      await widget.api.revokeDevice(device.id);
      await load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
      }
    }
  }
}

class _ServiceCard extends StatelessWidget {
  const _ServiceCard({required this.data});
  final ServiceOverview data;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: AppColors.ink,
      borderRadius: BorderRadius.circular(AppRadius.prominent),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const BrandAvatar(size: 44, inverted: true),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'PUBLIC MODEL',
                    style: TextStyle(
                      color: Color(0xff8f9094),
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.5,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    data.model,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 19,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
              decoration: BoxDecoration(
                color: const Color(0xff193b31),
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Row(
                children: [
                  StatusDot(active: true, size: 6),
                  SizedBox(width: 6),
                  Text(
                    'ONLINE',
                    style: TextStyle(
                      color: Color(0xff7be0c3),
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 20),
        InkWell(
          borderRadius: BorderRadius.circular(AppRadius.control),
          onTap: () {
            Clipboard.setData(ClipboardData(text: '${data.publicBaseUrl}/v1'));
            ScaffoldMessenger.of(
              context,
            ).showSnackBar(const SnackBar(content: Text('Base URL 已复制')));
          },
          child: Container(
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              color: const Color(0xff2c2d30),
              borderRadius: BorderRadius.circular(AppRadius.control),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'API BASE URL',
                        style: TextStyle(color: Color(0xff8f9094), fontSize: 9),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        '${data.publicBaseUrl}/v1',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Color(0xffb9f5e4),
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                const Icon(
                  Icons.copy_rounded,
                  color: Color(0xffb7b7ba),
                  size: 18,
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 13),
        Row(
          children: [
            _DarkMetric(
              label: '运行核心',
              value:
                  '${data.runtime.toUpperCase()} · ${data.database.toUpperCase()}',
            ),
            _DarkMetric(
              label: '最长等待',
              value: '${(data.timeoutSeconds / 60).round()} 分钟',
            ),
            _DarkMetric(
              label: '流式节奏',
              value: '${data.chunkChars} 字 / ${data.chunkDelayMs}ms',
            ),
          ],
        ),
      ],
    ),
  );
}

class _DarkMetric extends StatelessWidget {
  const _DarkMetric({required this.label, required this.value});
  final String label, value;
  @override
  Widget build(BuildContext context) => Expanded(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(color: Color(0xff85868a), fontSize: 9),
        ),
        const SizedBox(height: 4),
        Text(
          value,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 10,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ),
  );
}

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.profile, required this.onEdit});
  final ModelProfile profile;
  final VoidCallback onEdit;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(17),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  profile.displayName,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              IconButton(
                onPressed: onEdit,
                icon: const Icon(Icons.edit_outlined, size: 20),
              ),
            ],
          ),
          Text(
            profile.bio,
            style: const TextStyle(color: AppColors.muted, height: 1.5),
          ),
          if (profile.skills.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 13),
              child: Wrap(
                spacing: 7,
                runSpacing: 7,
                children: profile.skills
                    .map(
                      (skill) => Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 9,
                          vertical: 5,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.soft,
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(
                          skill,
                          style: const TextStyle(fontSize: 10),
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
        ],
      ),
    ),
  );
}

class _DeviceCard extends StatelessWidget {
  const _DeviceCard({
    required this.device,
    required this.current,
    required this.onTap,
  });
  final Device device;
  final bool current;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Card(
    child: ListTile(
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(horizontal: 15, vertical: 7),
      leading: Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(
          color: current ? AppColors.accentSoft : AppColors.soft,
          borderRadius: BorderRadius.circular(AppRadius.control),
        ),
        child: Icon(
          device.platform.contains('android') || device.platform.contains('ios')
              ? Icons.smartphone_rounded
              : Icons.computer_rounded,
          color: current ? AppColors.accent : AppColors.muted,
          size: 21,
        ),
      ),
      title: Row(
        children: [
          Expanded(
            child: Text(
              device.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          if (current)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
              decoration: BoxDecoration(
                color: AppColors.accentSoft,
                borderRadius: BorderRadius.circular(20),
              ),
              child: const Text(
                '当前设备',
                style: TextStyle(
                  fontSize: 9,
                  color: AppColors.accent,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
        ],
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 5),
        child: Text(
          '${device.model.isNotEmpty ? device.model : device.platform} · ${relativeTime(device.lastSeenAt)}',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
      ),
      trailing: StatusDot(active: device.active),
    ),
  );
}

class _DeviceFact extends StatelessWidget {
  const _DeviceFact({required this.label, required this.value});
  final String label, value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 88,
          child: Text(label, style: const TextStyle(color: AppColors.muted)),
        ),
        Expanded(
          child: Text(
            value.trim().isEmpty ? '—' : value,
            textAlign: TextAlign.end,
          ),
        ),
      ],
    ),
  );
}

class _ProfileSheet extends StatefulWidget {
  const _ProfileSheet({required this.profile});
  final ModelProfile profile;
  @override
  State<_ProfileSheet> createState() => _ProfileSheetState();
}

class _ProfileSheetState extends State<_ProfileSheet> {
  late final TextEditingController name, bio, skills;
  @override
  void initState() {
    super.initState();
    name = TextEditingController(text: widget.profile.displayName);
    bio = TextEditingController(text: widget.profile.bio);
    skills = TextEditingController(text: widget.profile.skills.join('、'));
  }

  @override
  void dispose() {
    name.dispose();
    bio.dispose();
    skills.dispose();
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
          '编辑公开资料',
          style: TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 7),
        const Text(
          '这些信息会随 /v1/models 返回给客户端。',
          style: TextStyle(color: AppColors.muted),
        ),
        const SizedBox(height: 18),
        TextField(
          controller: name,
          decoration: const InputDecoration(labelText: '显示名称'),
        ),
        const SizedBox(height: 11),
        TextField(
          controller: bio,
          minLines: 3,
          maxLines: 5,
          decoration: const InputDecoration(labelText: '一句话说明'),
        ),
        const SizedBox(height: 11),
        TextField(
          controller: skills,
          decoration: const InputDecoration(
            labelText: '能力标签',
            helperText: '使用逗号或顿号分隔',
          ),
        ),
        const SizedBox(height: 18),
        FilledButton(
          onPressed: () {
            if (name.text.trim().isEmpty || bio.text.trim().isEmpty) return;
            Navigator.pop(
              context,
              ModelProfile(
                displayName: name.text.trim(),
                bio: bio.text.trim(),
                skills: skills.text
                    .split(RegExp('[,，、]'))
                    .map((item) => item.trim())
                    .where((item) => item.isNotEmpty)
                    .toList(),
              ),
            );
          },
          child: const Text('保存公开资料'),
        ),
      ],
    ),
  );
}
