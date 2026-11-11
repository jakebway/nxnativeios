#version 450
layout(location = 0) in vec2 uv;
layout(location = 0) out vec4 color;
layout(binding = 0) uniform sampler2D tex;
layout(binding = 1) uniform Params { vec4 tint; int mode; } p;
void main() {
    vec4 c = texture(tex, uv) * p.tint;
    if (p.mode == 1) c.rgb = vec3(dot(c.rgb, vec3(0.299, 0.587, 0.114)));
    color = c;
}
