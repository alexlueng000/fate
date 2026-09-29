# 网站微信内 JSAPI 支付配置

## 本次问题与修复

截图中的“该商户暂时不支持通过长按识别二维码完成支付”发生在 Native 二维码长按识别场景。不能用跳转 Native `code_url` 代替 JSAPI 支付。

网站 `/pricing` 和 `/membership` 现在按浏览器选择渠道：微信内通过公众号网页授权取得 openid，后端调用 `/v3/pay/transactions/jsapi`，前端用 `WeixinJSBridge.invoke('getBrandWCPayRequest')` 调起收银台；其他浏览器继续 Native 扫码。界面不再提示长按二维码付款。未开通 JSAPI 时明确提示改用电脑扫码，不会生成假的 JSAPI 订单。

## 微信后台配置

1. 准备具有网页授权能力的公众号（通常为认证服务号）。在微信支付商户平台开通 JSAPI 产品权限，将该公众号 AppID 与实际收款商户号绑定并完成授权确认。不要填写历史小程序 AppID，也不要使用网站扫码登录的开放平台 AppID。
2. 在公众号后台配置“网页授权域名”：`fateinsight.site`；如果使用第二个域名，也配置 `yizhanmaster.site`。域名不含协议与路径，按后台提示将微信提供的校验文件部署到网站根目录；文件必须使用微信实际下载的内容。
3. 在商户平台“产品中心 → 开发配置”配置 JSAPI 支付授权目录。当前支付页面 `/pricing`、`/membership` 对应根目录 `https://fateinsight.site/`；若使用第二个域名，增加 `https://yizhanmaster.site/`。必须与用户实际打开的协议、域名一致，末尾保留 `/`。若部署启用了 trailingSlash 或路径前缀，请按实际支付页面目录调整，不能照搬。
4. 支付通知地址仍为 `https://api.fateinsight.site/api/webhooks/wechatpay`。它是服务器支付通知地址，不是网页授权域名或支付授权目录。

参考官方文档：
- [JSAPI 接入准备](https://pay.wechatpay.cn/doc/v3/merchant/4015423216)
- [支付授权目录](https://pay.wechatpay.cn/doc/v3/merchant/4013287088)
- [调起支付](https://pay.wechatpay.cn/doc/v3/merchant/4012791857)
- [支付签名](https://pay.wechatpay.cn/doc/v3/merchant/4012365339)

## 后端环境变量

在服务器后端环境中填写，重启服务生效。不要将 Secret、私钥或 API v3 Key 放进 `NEXT_PUBLIC_*`、Git 或聊天记录。

```dotenv
WECHAT_PAY_MODE=prod
WECHAT_JSAPI_ENABLED=true
WECHAT_JSAPI_APPID=公众号AppID
WECHAT_JSAPI_SECRET=该公众号AppSecret
WECHAT_JSAPI_ORIGINS=https://fateinsight.site,https://yizhanmaster.site

# 沿用已配置的商户号、商户 API 证书序列号和商户私钥
WECHAT_PAY_MCHID=商户号
WECHAT_PAY_MERCHANT_SERIAL_NO=商户API证书序列号
WECHAT_PAY_PRIVATE_KEY_PATH=/实际安全路径/apiclient_key.pem
WECHAT_PAY_NOTIFY_URL=https://api.fateinsight.site/api/webhooks/wechatpay
WECHAT_API_V3_KEY=商户APIv3密钥
WECHAT_PLATFORM_PUBLIC_KEY_PATH=/实际安全路径/wechatpay_public_key.pem
# JWT_SECRET 使用现有的强随机密钥（至少32字符），勿使用默认值
```

`WECHAT_PAY_APPID` 仍用于 Native 支付；新增 `WECHAT_JSAPI_APPID` 专用于公众号支付，二者可以相同，也可以是绑定到同一商户号的不同 AppID。`WX_APPID/WX_SECRET` 是历史小程序配置，本流程不使用。

无需为本流程配置 `wx.config` 或 `jsapi_ticket`：当前直接调用微信浏览器内置支付 Bridge。公众号网页授权域名与 JS 接口安全域名是不同配置。

## 流程与上线验收

- 登录网站后点击套餐，后端签发十分钟有效、绑定当前用户/商品/随机 state 的授权凭据。浏览器只把随机 state 发给微信，凭据保存在当前标签页 sessionStorage。
- 授权回来后先验证 state 和登录用户绑定，后端用一次性 code 换取公众号 openid；金额始终读取服务器商品，不接受客户端金额或 openid。
- 后端验证微信下单响应签名后返回 RSA 支付参数。用户点击“微信支付”确认；取消后可以在同一订单上重新调起。
- 仅服务器支付回调确认订单 PAID 后展示成功和发放权益，Bridge 的成功回调本身不发放权益。
- 同时部署后端和前端。在微信内从 `/pricing`、`/membership` 分别检查授权、取消、重试、付款成功和额度到账；在电脑浏览器检查 Native 二维码。
- 检查授权失效、未开通 JSAPI、商品下架时的提示。禁用开关可停止新的微信内授权，电脑扫码继续可用。
- 本地测试采用模拟微信服务，不能证明商户权限、域名审核、真实付款回调或资金到账已通过。上线必须完成真实微信客户端的小额交易验收。

## 常见问题

- `redirect_uri` 域名错误：检查公众号“网页授权域名”和校验文件，与当前网站域名一致。
- 支付目录未授权：检查商户“支付授权目录”，不是 API 域名。
- AppID 与商户号不匹配：完成公众号 AppID 与收款商户号的授权绑定。
- openid 与 AppID 不匹配：本流程由同一公众号授权取 openid；勿替换为小程序 openid。
- 授权失败或已过期：重新选择套餐；一次性 code 不会自动重试。
