// Contesto WebGL2, triangolo fullscreen, FBO, programmi, info renderer, context loss.

export interface DemogenInfo {
  webgl2: boolean;
  renderer: string;
  vendor: string;
  version: string;
  extensions: string[];
  maxTextureSize: number;
}

export function isSoftwareRenderer(name: string): boolean {
  const n = name.toLowerCase();
  return (
    n.includes("swiftshader") ||
    n.includes("llvmpipe") ||
    n.includes("softpipe") ||
    n.includes("software")
  );
}

/** Contesto WebGL2. Gli attributi valgono solo alla PRIMA getContext sul canvas:
 *  preserveDrawingBuffer va deciso qui (l'harness lo vuole per toDataURL). */
export function createGL(canvas: HTMLCanvasElement, preserveDrawingBuffer = false): WebGL2RenderingContext {
  const gl = canvas.getContext("webgl2", {
    antialias: false,
    alpha: false,
    depth: false,
    stencil: false,
    powerPreference: "high-performance",
    preserveDrawingBuffer,
  });
  if (!gl) throw new Error("WebGL2 non disponibile");
  return gl;
}

export function rendererInfo(gl: WebGL2RenderingContext): DemogenInfo {
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  const renderer = ext
    ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL))
    : String(gl.getParameter(gl.RENDERER));
  const vendor = ext
    ? String(gl.getParameter(ext.UNMASKED_VENDOR_WEBGL))
    : String(gl.getParameter(gl.VENDOR));
  return {
    webgl2: true,
    renderer,
    vendor,
    version: String(gl.getParameter(gl.VERSION)),
    extensions: gl.getSupportedExtensions() ?? [],
    maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
  };
}

export function compileShader(
  gl: WebGL2RenderingContext,
  type: number,
  src: string,
): WebGLShader {
  const sh = gl.createShader(type);
  if (!sh) throw new Error("createShader fallita");
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error(`Errore compilazione shader:\n${log}\n--- sorgente ---\n${src}`);
  }
  return sh;
}

export function createProgram(gl: WebGL2RenderingContext, fragSrc: string): WebGLProgram {
  const vs = compileShader(gl, gl.VERTEX_SHADER, VERT);
  let fs: WebGLShader;
  try {
    fs = compileShader(gl, gl.FRAGMENT_SHADER, fragSrc);
  } catch (e) {
    gl.deleteShader(vs);
    throw e;
  }
  const prog = gl.createProgram();
  if (!prog) throw new Error("createProgram fallita");
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  const ok = gl.getProgramParameter(prog, gl.LINK_STATUS);
  const log = ok ? "" : gl.getProgramInfoLog(prog);
  gl.deleteShader(vs); // gli shader servono solo fino al link (anche se fallisce)
  gl.deleteShader(fs);
  if (!ok) {
    gl.deleteProgram(prog);
    throw new Error(`Errore di link:\n${log}`);
  }
  return prog;
}

export const VERT = `#version 300 es
layout(location = 0) in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

/** Triangolo fullscreen nel VBO 0; ritorna il buffer (da liberare in dispose). */
export function bindFullscreenTriangle(gl: WebGL2RenderingContext): WebGLBuffer | null {
  const vbo = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  return vbo;
}

export interface FBO {
  fbo: WebGLFramebuffer;
  tex: WebGLTexture;
  width: number;
  height: number;
}

export function createFBO(gl: WebGL2RenderingContext, w: number, h: number): FBO {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const fbo = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) {
    throw new Error("FBO incompleto");
  }
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  return { fbo, tex, width: w, height: h };
}

export function resizeFBO(gl: WebGL2RenderingContext, target: FBO, w: number, h: number): void {
  if (target.width === w && target.height === h) return;
  gl.bindTexture(gl.TEXTURE_2D, target.tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  target.width = w;
  target.height = h;
}

export function deleteFBO(gl: WebGL2RenderingContext, target: FBO): void {
  gl.deleteFramebuffer(target.fbo);
  gl.deleteTexture(target.tex);
}
