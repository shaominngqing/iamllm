import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart' show Colors;
import 'package:mobile_scanner/mobile_scanner.dart';
import '../pairing_payload.dart';

class ScanPairingScreen extends StatefulWidget {
  const ScanPairingScreen({super.key});

  @override
  State<ScanPairingScreen> createState() => _ScanPairingScreenState();
}

class _ScanPairingScreenState extends State<ScanPairingScreen> {
  final controller = MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
    detectionSpeed: DetectionSpeed.noDuplicates,
    facing: CameraFacing.back,
  );
  bool handling = false;
  String notice = '';

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> detect(BarcodeCapture capture) async {
    if (handling) return;
    final raw = capture.barcodes
        .map((item) => item.rawValue)
        .whereType<String>()
        .firstOrNull;
    if (raw == null) return;
    final payload = PairingPayload.parse(raw);
    if (payload == null) {
      setState(() => notice = '这不是 iamllm 的配对二维码');
      Future<void>.delayed(const Duration(seconds: 2), () {
        if (mounted) setState(() => notice = '');
      });
      return;
    }
    handling = true;
    await controller.stop();
    if (mounted) Navigator.pop(context, payload);
  }

  @override
  Widget build(BuildContext context) => CupertinoPageScaffold(
    backgroundColor: CupertinoColors.black,
    child: Stack(
      fit: StackFit.expand,
      children: [
        MobileScanner(
          controller: controller,
          fit: BoxFit.cover,
          tapToFocus: true,
          onDetect: detect,
        ),
        const _ScannerShade(),
        SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 8,
                ),
                child: Row(
                  children: [
                    _RoundButton(
                      icon: CupertinoIcons.xmark,
                      onPressed: () => Navigator.pop(context),
                    ),
                    const Expanded(
                      child: Text(
                        '扫描配对二维码',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: CupertinoColors.white,
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    ValueListenableBuilder(
                      valueListenable: controller,
                      builder: (context, state, _) => _RoundButton(
                        icon: state.torchState == TorchState.on
                            ? CupertinoIcons.bolt_fill
                            : CupertinoIcons.bolt,
                        onPressed: controller.toggleTorch,
                      ),
                    ),
                  ],
                ),
              ),
              const Spacer(),
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 180),
                child: notice.isEmpty
                    ? const Text(
                        '将网页控制台中的二维码放入框内',
                        key: ValueKey('hint'),
                        style: TextStyle(
                          color: CupertinoColors.white,
                          fontSize: 14,
                        ),
                      )
                    : Container(
                        key: const ValueKey('notice'),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 9,
                        ),
                        decoration: BoxDecoration(
                          color: CupertinoColors.systemRed.withValues(
                            alpha: .9,
                          ),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          notice,
                          style: const TextStyle(
                            color: CupertinoColors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
              ),
              const SizedBox(height: 46),
            ],
          ),
        ),
      ],
    ),
  );
}

class _RoundButton extends StatelessWidget {
  const _RoundButton({required this.icon, required this.onPressed});
  final IconData icon;
  final VoidCallback onPressed;
  @override
  Widget build(BuildContext context) => CupertinoButton(
    padding: EdgeInsets.zero,
    onPressed: onPressed,
    child: Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: CupertinoColors.black.withValues(alpha: .42),
        shape: BoxShape.circle,
      ),
      alignment: Alignment.center,
      child: Icon(icon, color: CupertinoColors.white, size: 18),
    ),
  );
}

class _ScannerShade extends StatelessWidget {
  const _ScannerShade();
  @override
  Widget build(BuildContext context) => CustomPaint(painter: _ScannerPainter());
}

class _ScannerPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final side = size.width - 64;
    final rect = Rect.fromCenter(
      center: Offset(size.width / 2, size.height * .43),
      width: side,
      height: side,
    );
    final path = Path()
      ..addRect(Offset.zero & size)
      ..addRRect(RRect.fromRectAndRadius(rect, const Radius.circular(28)))
      ..fillType = PathFillType.evenOdd;
    canvas.drawPath(path, Paint()..color = Colors.black.withValues(alpha: .48));

    final line = Paint()
      ..color = CupertinoColors.white
      ..strokeWidth = 4
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    const corner = 34.0;
    final radius = const Radius.circular(28);
    final rrect = RRect.fromRectAndRadius(rect, radius);
    final border = Path()
      ..moveTo(rrect.left + corner, rrect.top)
      ..lineTo(rrect.left + 28, rrect.top)
      ..quadraticBezierTo(rrect.left, rrect.top, rrect.left, rrect.top + 28)
      ..lineTo(rrect.left, rrect.top + corner)
      ..moveTo(rrect.right - corner, rrect.top)
      ..lineTo(rrect.right - 28, rrect.top)
      ..quadraticBezierTo(rrect.right, rrect.top, rrect.right, rrect.top + 28)
      ..lineTo(rrect.right, rrect.top + corner)
      ..moveTo(rrect.left, rrect.bottom - corner)
      ..lineTo(rrect.left, rrect.bottom - 28)
      ..quadraticBezierTo(
        rrect.left,
        rrect.bottom,
        rrect.left + 28,
        rrect.bottom,
      )
      ..lineTo(rrect.left + corner, rrect.bottom)
      ..moveTo(rrect.right, rrect.bottom - corner)
      ..lineTo(rrect.right, rrect.bottom - 28)
      ..quadraticBezierTo(
        rrect.right,
        rrect.bottom,
        rrect.right - 28,
        rrect.bottom,
      )
      ..lineTo(rrect.right - corner, rrect.bottom);
    canvas.drawPath(border, line);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
