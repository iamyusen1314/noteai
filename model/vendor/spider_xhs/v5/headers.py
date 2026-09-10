"""Pure header helpers extracted unchanged from Spider_XHS 7077c88 params/http."""

import math,random,time

from collections.abc import Mapping

from typing import Any,Optional

PC_LOGIN_ACCEPT_LANGUAGE = 'zh-CN,zh;q=0.9'

PC_BUSINESS_ACCEPT_LANGUAGE = 'zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7,ja;q=0.6'

PC_SEC_CH_UA = (
    '"Not;A=Brand";v="8", "Chromium";v="152", '
    '"Google Chrome";v="152"'
)

PC_CURRENT_BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36'
)

PC_NAVIGATION_HEADER_ORDER = (
    'upgrade-insecure-requests', 'user-agent', 'sec-ch-ua',
    'sec-ch-ua-mobile', 'sec-ch-ua-platform', 'accept', 'accept-encoding',
    'accept-language', 'cookie', 'priority', 'sec-fetch-dest',
    'sec-fetch-mode', 'sec-fetch-site', 'sec-fetch-user',
)

PC_HONEYPOT_HEADER_ORDER = (
    'sec-ch-ua-platform', 'referer', 'user-agent', 'accept', 'sec-ch-ua',
    'content-type', 'sec-ch-ua-mobile', 'accept-encoding', 'accept-language',
    'cookie', 'origin', 'priority', 'sec-fetch-dest', 'sec-fetch-mode',
    'sec-fetch-site',
)

PC_SECURITY_HEADER_ORDER = (
    'sec-ch-ua-platform', 'referer', 'sec-ch-ua', 'sec-ch-ua-mobile',
    'x-t', 'x-s-common', 'user-agent', 'accept', 'content-type', 'x-s',
    'accept-encoding', 'accept-language', 'cookie', 'origin', 'priority',
    'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site',
)

PC_SEM_HEADER_ORDER = (
    'sec-ch-ua-platform', 'referer', 'sec-ch-ua', 'sec-ch-ua-mobile',
    'x-t', 'x-s-common', 'user-agent', 'accept', 'x-s', 'accept-encoding',
    'accept-language', 'origin', 'priority', 'sec-fetch-dest',
    'sec-fetch-mode', 'sec-fetch-site',
)

PC_SIGNED_POST_HEADER_ORDER = (
    'sec-ch-ua-platform', 'referer', 'sec-ch-ua', 'x-xray-traceid',
    'sec-ch-ua-mobile', 'x-t', 'x-b3-traceid', 'x-s-common',
    'user-agent', 'accept', 'content-type', 'x-s', 'accept-encoding',
    'accept-language', 'cookie', 'origin', 'priority', 'sec-fetch-dest',
    'sec-fetch-mode', 'sec-fetch-site',
)

PC_SIGNED_GET_HEADER_ORDER = (
    'sec-ch-ua-platform', 'referer', 'sec-ch-ua', 'x-xray-traceid',
    'sec-ch-ua-mobile', 'x-t', 'x-b3-traceid', 'x-s-common',
    'user-agent', 'accept', 'x-s', 'accept-encoding', 'accept-language',
    'cookie', 'origin', 'priority', 'sec-fetch-dest', 'sec-fetch-mode',
    'sec-fetch-site',
)

PC_BUSINESS_SIGNED_POST_HEADER_ORDER = (
    'referer', 'x-xray-traceid', 'x-t', 'x-b3-traceid', 'x-s-common',
    'user-agent', 'accept', 'content-type', 'x-s', 'accept-encoding',
    'accept-language', 'cookie', 'origin', 'priority', 'sec-fetch-dest',
    'sec-fetch-mode', 'sec-fetch-site',
)

PC_BUSINESS_SIGNED_GET_HEADER_ORDER = (
    'referer', 'x-xray-traceid', 'x-t', 'x-b3-traceid', 'x-s-common',
    'user-agent', 'accept', 'x-s', 'accept-encoding', 'accept-language',
    'cookie', 'origin', 'priority', 'sec-fetch-dest', 'sec-fetch-mode',
    'sec-fetch-site',
)

PC_BUSINESS_CDEVICE_GET_HEADER_ORDER = (
    'referer', 'x-xray-traceid', 'c_device_id', 'x-t', 'x-b3-traceid',
    'x-s-common', 'user-agent', 'accept', 'x-s', 'accept-encoding',
    'accept-language', 'cookie', 'origin', 'priority', 'sec-fetch-dest',
    'sec-fetch-mode', 'sec-fetch-site',
)

PC_LIVE_POST_HEADER_ORDER = (
    'referer', 'xy-common-params', 'x-t', 'x-s-common',
    'x-ratelimit-meta', 'accept', 'content-type', 'x-s', 'user-agent',
    'accept-encoding', 'accept-language', 'cookie', 'origin', 'priority',
    'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site',
)

PC_LIVE_GET_HEADER_ORDER = (
    'referer', 'xy-common-params', 'x-t', 'x-s-common',
    'x-ratelimit-meta', 'accept', 'x-s', 'user-agent', 'accept-encoding',
    'accept-language', 'cookie', 'origin', 'priority', 'sec-fetch-dest',
    'sec-fetch-mode', 'sec-fetch-site',
)

PC_RAP_POST_HEADER_ORDER = (
    'referer', 'x-xray-traceid', 'x-t', 'x-b3-traceid', 'x-s-common',
    'x-rap-param', 'accept', 'content-type', 'x-s', 'user-agent',
    'accept-encoding', 'accept-language', 'cookie', 'origin', 'priority',
    'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site',
)

PC_XY_RAP_POST_HEADER_ORDER = (
    # Chrome's homefeed/feed requests place the sharding header first.
    'xy-direction', 'referer', 'x-xray-traceid', 'x-t', 'x-b3-traceid',
    'x-s-common', 'x-rap-param', 'accept', 'content-type', 'x-s',
    'user-agent', 'accept-encoding', 'accept-language', 'cookie', 'origin',
    'priority', 'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site',
)

PC_RAP_GET_HEADER_ORDER = (
    'referer', 'x-xray-traceid', 'x-t', 'x-b3-traceid', 'x-s-common',
    'x-rap-param', 'user-agent', 'accept', 'x-s', 'accept-encoding',
    'accept-language', 'cookie', 'origin', 'priority', 'sec-fetch-dest',
    'sec-fetch-mode', 'sec-fetch-site',
)

def generate_x_b3_traceid(len=16):
    x_b3_traceid = ""
    for t in range(len):
        x_b3_traceid += "abcdef0123456789"[math.floor(16 * random.random())]
    return x_b3_traceid

_xray_seq = [int(random.random() * 0x7fffff)]

def generate_xray_traceid():
    """本地生成 x-xray-traceid（还原自 xhs_xray.js traceId）：
    hex16((now_ms<<23)|seq) + hex16(random64)。追踪头，不参与签名校验。"""
    now_ms = int(time.time() * 1000)
    _xray_seq[0] = (_xray_seq[0] + 1) & 0x7fffff
    part1 = format(((now_ms << 23) | _xray_seq[0]) & 0xffffffffffffffff, 'x').rjust(16, '0')
    rnd = (random.getrandbits(32) << 32) | random.getrandbits(32)
    part2 = format(rnd, 'x').rjust(16, '0')
    return part1 + part2

def generate_xy_direction(user_id: str) -> int:
    """
    PC 端 xy-direction = murmurHash3_32(userId, 151488) % 100 + 1
    结果会缓存到 localStorage.xhs_sharding_key
    """
    if not user_id:
        return 0
    return murmur_hash3_32(user_id, 151488) % 100 + 1

def _string_to_utf8_bytes(s: str):
    return list(s.encode('utf-8'))

def murmur_hash3_32(key: str, seed: int = 0) -> int:
    """对齐小红书 index.bundle 中的 murmurHash3_32"""
    data = _string_to_utf8_bytes(key)
    length = len(data)
    h = seed & 0xffffffff
    nblocks = length // 4

    for i in range(nblocks):
        k = (data[4*i]
             | (data[4*i+1] << 8)
             | (data[4*i+2] << 16)
             | (data[4*i+3] << 24)) & 0xffffffff
        k = (k * 0xcc9e2d51) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        k = (k * 0x1b873593) & 0xffffffff
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xffffffff
        h = (h * 5 + 0xe6546b64) & 0xffffffff

    tail_index = 4 * nblocks
    k = 0
    rem = length % 4
    if rem == 3:
        k ^= data[tail_index + 2] << 16
    if rem >= 2:
        k ^= data[tail_index + 1] << 8
    if rem >= 1:
        k ^= data[tail_index]
        k = (k * 0xcc9e2d51) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        k = (k * 0x1b873593) & 0xffffffff
        h ^= k

    h ^= length
    h ^= (h >> 16)
    h = (h * 0x85ebca6b) & 0xffffffff
    h ^= (h >> 13)
    h = (h * 0xc2b2ae35) & 0xffffffff
    h ^= (h >> 16)
    return h

def get_request_headers_template(
    sign_context=None,
    *,
    method='POST',
    accept_language=PC_BUSINESS_ACCEPT_LANGUAGE,
    has_body=None,
    include_client_hints=True,
    include_trace_headers=True,
):
    context = sign_context or {}
    user_agent = context.get(
        'userAgent',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36',
    )
    headers = {
        'referer': 'https://www.xiaohongshu.com/',
        'x-t': '',
        'x-s-common': '',
        'user-agent': user_agent,
        'accept': 'application/json, text/plain, */*',
        'x-s': '',
        'accept-language': str(accept_language),
        'origin': 'https://www.xiaohongshu.com',
        'priority': 'u=1, i',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
    }
    if include_trace_headers:
        headers['x-xray-traceid'] = generate_xray_traceid()
        headers['x-b3-traceid'] = ''
    if include_client_hints:
        headers['sec-ch-ua-platform'] = '"Windows"'
        headers['sec-ch-ua'] = context.get('secChUa', PC_SEC_CH_UA)
        headers['sec-ch-ua-mobile'] = '?0'
    if has_body is None:
        has_body = str(method).upper() != 'GET'
    if has_body:
        headers['content-type'] = 'application/json;charset=UTF-8'
    return headers

def build_pc_business_headers(headers, cookies, *, api, method='POST'):
    upper_method = str(method).upper()
    has_rap = 'x-rap-param' in {str(key).lower() for key in headers}
    has_xy = 'xy-direction' in {str(key).lower() for key in headers}
    has_client_hints = 'sec-ch-ua-platform' in {str(key).lower() for key in headers}
    has_device_header = 'c_device_id' in {str(key).lower() for key in headers}
    if not has_client_hints and has_device_header:
        order = PC_BUSINESS_CDEVICE_GET_HEADER_ORDER
    elif not has_client_hints and has_xy:
        order = PC_XY_RAP_POST_HEADER_ORDER
    elif not has_client_hints and has_rap and upper_method == 'GET':
        order = PC_RAP_GET_HEADER_ORDER
    elif not has_client_hints and has_rap:
        order = PC_RAP_POST_HEADER_ORDER
    elif not has_client_hints and not has_rap and not has_xy:
        order = (
            PC_BUSINESS_SIGNED_GET_HEADER_ORDER
            if upper_method == 'GET'
            else PC_BUSINESS_SIGNED_POST_HEADER_ORDER
        )
    elif has_xy:
        order = PC_XY_RAP_POST_HEADER_ORDER
    elif has_rap and upper_method == 'GET':
        order = PC_RAP_GET_HEADER_ORDER
    elif has_rap:
        order = PC_RAP_POST_HEADER_ORDER
    elif upper_method == 'GET':
        order = PC_SIGNED_GET_HEADER_ORDER
    else:
        order = PC_SIGNED_POST_HEADER_ORDER
    if 'content-type' not in {str(key).lower() for key in headers}:
        order = tuple(key for key in order if key != 'content-type')
    # Message-page bootstrap captures include these cache controls in this
    # exact relative position.
    lower_keys = {str(key).lower() for key in headers}
    order = list(order)
    if 'cache-control' in lower_keys and 'cache-control' not in order:
        anchor = order.index('cookie') if 'cookie' in order else order.index('origin')
        order.insert(anchor, 'cache-control')
    if 'pragma' in lower_keys and 'pragma' not in order:
        anchor = order.index('priority') if 'priority' in order else len(order)
        order.insert(anchor, 'pragma')
    return ordered_wire_headers(
        headers,
        order=tuple(order),
        cookies=cookies,
    )

DEFAULT_ACCEPT_ENCODING = 'gzip, deflate, br, zstd'

def _cookie_header(cookies: Any) -> str:
    if not cookies:
        return ''
    if isinstance(cookies, str):
        return cookies
    if isinstance(cookies, Mapping):
        return '; '.join(f'{key}={value}' for key, value in cookies.items())
    try:
        return '; '.join(f'{key}={value}' for key, value in cookies.items())
    except AttributeError as exc:
        raise TypeError('transport cookies must be a string or mapping') from exc

def ordered_wire_headers(
    headers: Optional[Mapping[str, Any]],
    *,
    order: tuple[str, ...] | list[str],
    cookies: Any = None,
    accept_encoding: str = DEFAULT_ACCEPT_ENCODING,
    strict: bool = True,
    optional: tuple[str, ...] | list[str] = (),
) -> dict[str, str]:
    """Inject Cookie/Accept-Encoding and enforce an observed Header contract.

    HTTP/2 pseudo headers and ``content-length`` remain libcurl's job.  The
    returned mapping owns the order of all ordinary browser-visible headers.
    """
    values = {
        str(key).lower(): str(value)
        for key, value in dict(headers or {}).items()
        if str(key).lower() != 'authority'
    }
    values.setdefault('accept-encoding', str(accept_encoding))
    cookie = _cookie_header(cookies)
    if cookie:
        values['cookie'] = cookie
    else:
        values.pop('cookie', None)

    normalized_order = tuple(str(key).lower() for key in order)
    optional_names = {str(key).lower() for key in optional}
    missing = [
        key for key in normalized_order
        if key not in values and key not in optional_names
    ]
    # Optional captured headers may be present in a route-specific request
    # without belonging to the shared canonical order.  Keep them after the
    # ordered fields rather than rejecting a valid Chrome capture.
    unexpected = sorted(set(values) - set(normalized_order) - optional_names)
    if missing or (strict and unexpected):
        raise RuntimeError(
            'wire header contract drifted: '
            f'missing={missing}, unexpected={unexpected}'
        )
    result = {
        key: values[key]
        for key in normalized_order
        if key in values
    }
    for key in values:
        if key in optional_names and key not in result:
            result[key] = values[key]
    return result
