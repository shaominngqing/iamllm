import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class SessionStore {
  static const _secure = FlutterSecureStorage();
  String baseUrl = '', accessToken = '', refreshToken = '', deviceId = '';
  Future<void> load() async {
    baseUrl = await _secure.read(key: 'base_url') ?? '';
    accessToken = await _secure.read(key: 'access_token') ?? '';
    refreshToken = await _secure.read(key: 'refresh_token') ?? '';
    deviceId = await _secure.read(key: 'device_id') ?? '';
  }

  Future<void> save({
    required String server,
    required String access,
    required String refresh,
    required String device,
  }) async {
    baseUrl = server.replaceAll(RegExp(r'/+$'), '');
    accessToken = access;
    refreshToken = refresh;
    deviceId = device;
    await Future.wait([
      _secure.write(key: 'base_url', value: baseUrl),
      _secure.write(key: 'access_token', value: accessToken),
      _secure.write(key: 'refresh_token', value: refreshToken),
      _secure.write(key: 'device_id', value: deviceId),
    ]);
  }

  Future<void> clear() async {
    baseUrl = '';
    accessToken = '';
    refreshToken = '';
    deviceId = '';
    await _secure.deleteAll();
  }

  bool get signedIn => baseUrl.isNotEmpty && refreshToken.isNotEmpty;
}
