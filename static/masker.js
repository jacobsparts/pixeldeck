"use strict";
const componentStyles = `
[hidden] {
        display: none !important;
}
:host > * {
	background-color: transparent;
}
button {
	background: none;
	border: none;
	padding: 0.25rem 0.5rem;
	border-radius: 4px;
	cursor: default;
	white-space: nowrap;
	font: inherit;
}
button:hover {
	background: #e8e8e8;
}
button:active {
	background: #d0d0d0;
}
`;

function createImage(url) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = url;
    });
}

class Masker extends HTMLElement {
	constructor() {
		super();
		this.attachShadow({ mode: 'open' });
		const style = document.createElement('style')
		style.textContent = componentStyles;
		this.shadowRoot.appendChild(style);


		this.body = document.createElement('div');
		this.body.style.height = '100%';
		this.shadowRoot.appendChild(this.body);

		this.canvas = document.createElement('canvas');
		Object.assign(this.canvas.style, {
			position: 'absolute',
			top: '0',
			left: '0',
			imageRendering: 'pixelated',
		});
		this.canvas.addEventListener('dragover', (event) => {
			event.preventDefault();
		});
		this.canvas.addEventListener('drop', (event) => {
			event.preventDefault();
			event.stopPropagation();
			const files = event.dataTransfer.files;
			if (files.length > 0) {
				const file = files[0];
				const dropEvent = new DragEvent('drop', {
					dataTransfer: event.dataTransfer,
					bubbles: true,
					composed: true,
				});
				Object.defineProperty(dropEvent, 'files', { value: files });
				this.dispatchEvent(dropEvent);
			}
		});
		this.ctx = this.canvas.getContext('2d');

		this.maskingCanvas = document.createElement('canvas');
		Object.assign(this.maskingCanvas.style, {
			position: 'absolute',
			top: '0',
			left: '0',
			imageRendering: 'pixelated',
			pointerEvents: 'none',
			opacity: '40%',
		});
		this.maskingCtx = this.maskingCanvas.getContext('2d');
		this.cleanupListeners = [];
		this._headless = false;
		this._src = null;
		this.rendered = false;
	}

	static get observedAttributes(){
		return ['src', 'headless'];
	}

	connectedCallback(){
		if(!this.rendered){
			this.rendered = true;
			this.renderMasker();
			this.loadSrc();
		}
	}

	disconnectedCallback(){
		for(const cleanup of this.cleanupListeners){
			cleanup();
		}
		this.cleanupListeners = [];
	}

	attributeChangedCallback(name, oldValue, newValue){
		if(name === 'src' && oldValue !== newValue){
			this.src = newValue;
		} else if(name === 'headless'){
			this.headless = newValue !== null && newValue !== 'false';
		}
	}

	get headless(){
		return this._headless;
	}

	set headless(value){
		this._headless = value === true || value === '' || value === 'true';
	}

	loadSrc(){
		if(!this._src || !this.rendered || !this.load){return}
		const url = this._src;
		createImage(url).then((img) => {
			if(this._src === url && this.isConnected){
				this.load(img);
			}
		});
	}


	set src(url) {
		if(!url){return}
		this._src = url;
		this.loadSrc();
	}

	get width(){
		return this.canvas.width;
	}

	get height(){
		return this.canvas.height;
	}

	get imageData() {
		return this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
	}

	get imageBlob() {
		return new Promise((resolve) => {
			this.canvas.toBlob((blob) => { resolve(blob) }, 'image/png');
		});
	}

	get maskBlob() {
		return this.maskImageDataBlob();
	}

	get maskAlphaBlob() {
		return this.maskAlphaImageDataBlob();
	}

	get maskAlphaImageData() {
		return this.maskAlphaImageDataValue();
	}

	renderMasker() {
		/*
		 * Init
		 */

		const body = this.body;

		const headless = this.headless;
		let isDrawing = false;
		let [lastX, lastY] = [null, null];
		let scaleFactor = 1; // canvas to viewport irrespective of zoom
		let scaleF = 0; // initial scale factor
		let offsetX = 0;
		let offsetY = 0;
		let zoomOffsetX = 0;
		let zoomOffsetY = 0;
		let originalImageData;
		let maskHistory = [], maskFuture = [];
		let cursorSize = 20;
		let cursorSizeScaled = 20;
		let drawMode = null; // null, 'brush', or 'box'
		let boxStartX, boxStartY, boxPreviewData;
		let circleCursor, slider;

		const canvas = this.canvas, ctx = this.ctx;
		const maskingCanvas = this.maskingCanvas, maskingCtx = this.maskingCtx;

		const imageContainer = document.createElement('div');
		imageContainer.style.position = 'relative';
		imageContainer.style.display = 'inline-block';
		imageContainer.appendChild(canvas);
		imageContainer.appendChild(maskingCanvas);

		
		this.load = (img) => {
			imageContainer.style.width = `${img.width}px`;
			imageContainer.style.height = `${img.height}px`;
			if(!headless){
				maskHistory = [];
				maskFuture = [maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height)];
			}
			maskingCanvas.width = canvas.width = img.width;
			maskingCanvas.height = canvas.height = img.height;
			maskingCtx.clearRect(0, 0, maskingCanvas.width, maskingCanvas.height);
			maskingCtx.lineWidth = 20;
			maskingCtx.lineCap = 'round';
			maskingCtx.strokeStyle = 'yellow';

			ctx.clearRect(0, 0, canvas.width, canvas.height);
			ctx.drawImage(img, 0, 0);
			imageContainer.style.opacity = '0.99999';
			requestAnimationFrame(() => {
				imageContainer.style.opacity = '';
			});
			if(!headless){
				originalImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
				slider.value = 60;
				slider.dispatchEvent(new Event('input'));
				circleCursor.hidden = true;
				zoomOffsetX = 0;
				zoomOffsetY = 0;
				resize();
			}
			this.dispatchEvent(new CustomEvent('load', {
                                bubbles: true,
                                composed: true,
                        }));
		}

		const mainBoard = document.createElement('div');
		mainBoard.style.overflow = 'hidden';
		mainBoard.style.height = '100%';
		mainBoard.appendChild(imageContainer);
		body.appendChild(mainBoard);

		const resizeCursor = () => {
			const adjustedCursorSize = cursorSize / scaleFactor;
			maskingCtx.lineWidth = Math.round(adjustedCursorSize);
			cursorSizeScaled = adjustedCursorSize * (1 + 0.1 * scaleF);
			if(circleCursor && !isNaN(cursorSizeScaled)){
				circleCursor.style.width = cursorSizeScaled+"px";
				circleCursor.style.height = cursorSizeScaled+"px";
			}
		}

		const resize = () => {
			scaleFactor = Math.min(mainBoard.clientWidth / canvas.width, mainBoard.clientHeight / canvas.height);
			scaleF = (scaleFactor-1)/0.1;
			imageContainer.style.transformOrigin = "center center";
			imageContainer.style.transform = `scale(${scaleFactor})`;
			offsetX = (canvas.width > mainBoard.clientWidth) ? (mainBoard.clientWidth - canvas.width) / 2 : 0;
			offsetY = -(canvas.height * (1 - scaleFactor) / 2);
			imageContainer.style.left = `${offsetX}px`;
			imageContainer.style.top = `${offsetY}px`;
			resizeCursor();
		}

		window.addEventListener('resize', resize);
		this.cleanupListeners.push(() => window.removeEventListener('resize', resize));


		/*
		 * Utility Functions
		 */

		const getMaskImageData = () => {
			const maskingImageData = maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height)
			const maskingPixelArray = maskingImageData.data;
			const imageData = ctx.createImageData(canvas.width, canvas.height);
			const pixelArray = imageData.data;
			for (let i = 0; i < maskingPixelArray.length; i+=4) {
				const isBlack = maskingPixelArray[i+3];
				pixelArray[i] = isBlack ? 255 : 0;       // Red channel
				pixelArray[i + 1] = isBlack ? 255 : 0;   // Green channel
				pixelArray[i + 2] = isBlack ? 255 : 0;   // Blue channel
				pixelArray[i + 3] = 255;                 // Alpha channel
			}
			return imageData;
		}

		// imageData -> Blob promise
		const imageDataBlob = (imageData) => {
			const canvas = document.createElement('canvas');
			canvas.width = imageData.width;
			canvas.height = imageData.height;
			const ctx = canvas.getContext('2d');
			ctx.putImageData(imageData, 0, 0);
			return new Promise((resolve) => {
				canvas.toBlob((blob) => { resolve(blob) }, 'image/png');
			});
		};

		/*
		 * Mask Draw
		 */

		circleCursor = document.createElement('div');
		circleCursor.style.pointerEvents = 'none';
		circleCursor.style.position = 'fixed';
		circleCursor.style.top = '0';
		circleCursor.style.left = '0';
		circleCursor.style.width = cursorSizeScaled+'px';
		circleCursor.style.height = cursorSizeScaled+'px';
		circleCursor.style.borderRadius = '50%';
		circleCursor.style.backgroundColor = 'rgba(255, 239, 0, 0.75)';
		circleCursor.hidden = true;
		body.appendChild(circleCursor);

		if(!headless){

		const start = (e) => {
			if(!drawMode){return}
			isDrawing = true;
			maskHistory.push(maskingCtx.getImageData(0, 0, canvas.width, canvas.height));
			maskFuture = [];
			if(drawMode === 'box'){
				boxStartX = e.offsetX;
				boxStartY = e.offsetY;
				boxPreviewData = maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height);
			} else {
				[lastX, lastY] = [null, null];
				draw(e);
			}
		}

                const draw = (e) => {
                        if(!drawMode){return}
			if(drawMode === 'brush'){
				circleCursor.style.top = (e.clientY - cursorSizeScaled / 2) + 'px';
				circleCursor.style.left = (e.clientX - cursorSizeScaled / 2) + 'px';
				circleCursor.hidden = false;
				circleCursor.style.backgroundColor = e.ctrlKey ? 'rgba(255, 0, 0, 0.5)' : 'rgba(255, 239, 0, 0.75)';
				body.style.cursor = 'none';
				if (isDrawing){
					maskingCtx.globalCompositeOperation = e.ctrlKey ? 'destination-out' : 'source-over';
					const X = e.offsetX, Y = e.offsetY;
					if(lastX === null){ [lastX, lastY] = [X, Y] }
					maskingCtx.beginPath();
					maskingCtx.moveTo(lastX, lastY);
					maskingCtx.lineTo(X, Y);
					maskingCtx.stroke();
					[lastX, lastY] = [X, Y];
				}
			} else if(drawMode === 'box'){
				circleCursor.hidden = true;
				body.style.cursor = 'crosshair';
				if(isDrawing){
					maskingCtx.putImageData(boxPreviewData, 0, 0);
					maskingCtx.globalCompositeOperation = e.ctrlKey ? 'destination-out' : 'source-over';
					const x = Math.min(boxStartX, e.offsetX);
					const y = Math.min(boxStartY, e.offsetY);
					const w = Math.abs(e.offsetX - boxStartX);
					const h = Math.abs(e.offsetY - boxStartY);
					maskingCtx.fillStyle = 'yellow';
					maskingCtx.fillRect(x, y, w, h);
				}
			}
                }

		canvas.addEventListener('mousedown', start);
		canvas.addEventListener('mousemove', draw);
		canvas.addEventListener('mouseout', () => {
			circleCursor.hidden = true;
			body.style.cursor = 'auto';
		});
		const mouseupHandler = () => {
			isDrawing = false;
			maskingCtx.globalCompositeOperation = 'source-over';
		};
		const keydownHandler = (e) => {
			if(e.key === 'Control' && drawMode === 'brush' && !circleCursor.hidden){
				circleCursor.style.backgroundColor = 'rgba(255, 0, 0, 0.5)';
			}
		};
		const keyupHandler = (e) => {
			if(e.key === 'Control' && drawMode === 'brush' && !circleCursor.hidden){
				circleCursor.style.backgroundColor = 'rgba(255, 239, 0, 0.75)';
			}
		};
		window.addEventListener('mouseup', mouseupHandler);
		document.addEventListener('keydown', keydownHandler);
		document.addEventListener('keyup', keyupHandler);
		this.cleanupListeners.push(() => window.removeEventListener('mouseup', mouseupHandler));
		this.cleanupListeners.push(() => document.removeEventListener('keydown', keydownHandler));
		this.cleanupListeners.push(() => document.removeEventListener('keyup', keyupHandler));
		canvas.addEventListener('mouseenter', (e) => {
			if (isDrawing && drawMode === 'brush'){
				start(e);
			}
		});

		/*
		 * Zoom
		 */

		const wheelHandler = (e) => {
			e.preventDefault();

			if(e.target.tagName !== "CANVAS"){
				return;
			}

			const oldScale = 1 + 0.1 * scaleF;
			const pointerX = e.offsetX;
			const pointerY = e.offsetY;

			scaleF = Math.min(scaleF - e.deltaY * 0.01, 100);
			const newScale = 1 + 0.1 * scaleF;

			if(newScale <= scaleFactor){
				zoomOffsetX = zoomOffsetY = 0;
				resize();
			} else {
				const left = offsetX + zoomOffsetX + (oldScale - newScale) * (pointerX - canvas.width / 2);
				const top = offsetY + zoomOffsetY + (oldScale - newScale) * (pointerY - canvas.height / 2);
				zoomOffsetX = left - offsetX;
				zoomOffsetY = top - offsetY;
				Object.assign(imageContainer.style, {
					transform: `scale(${newScale})`,
					left: `${left}px`,
					top: `${top}px`
				});
				resizeCursor();
				circleCursor.style.top = (e.clientY - cursorSizeScaled / 2) + 'px';
				circleCursor.style.left = (e.clientX - cursorSizeScaled / 2) + 'px';
			}
		};

		body.addEventListener("wheel", wheelHandler, { passive: false });


		/*
		 * Tool Board
		 */

		const toolBoard = document.createElement('div');
		toolBoard.style = "display: flex; flex-wrap: wrap; align-items: center; gap: 0.375rem; justify-content: center; background: #fff; border-top: 1px solid #ddd; padding: 0 0.5rem; min-height: 2rem; font-size: 0.8125rem; font-family: system-ui, -apple-system, sans-serif; user-select: none; position: fixed; bottom: 0; left: 0; right: 0; z-index: 50;";

		const undoButton = document.createElement('button');
		undoButton.innerHTML = "↶";
		undoButton.onclick = () => {
			if (maskHistory.length){
				maskFuture.push(maskingCtx.getImageData(0, 0, canvas.width, canvas.height));
				maskingCtx.putImageData(maskHistory.pop(), 0, 0);
			}
		};
		toolBoard.appendChild(undoButton);

		const redoButton = document.createElement('button');
		redoButton.innerHTML = "↷";
		redoButton.onclick = () => {
			if (maskFuture.length){
				maskHistory.push(maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height));
				maskingCtx.putImageData(maskFuture.pop(), 0, 0);
			}
		};
		toolBoard.appendChild(redoButton);

		slider = document.createElement('input');
		slider.name = "slider";
		slider.type = "range";
		slider.min = 1;
		slider.max = 100;
		slider.step = 1;
		slider.value = 60;
		slider.oninput = function () {
			const minv = Math.log(2);
			const maxv = Math.log(150);
			const scale = (maxv-minv) / 100;
			cursorSize = Math.exp(minv + scale*(this.value-1));
			resizeCursor();
			circleCursor.hidden = false;
		}
		slider.addEventListener('mouseup', function () {
			circleCursor.hidden = true;
		});
		slider.dispatchEvent(new Event('input'));
		toolBoard.appendChild(slider);

		const brushButton = document.createElement('button');
		brushButton.innerHTML = "Brush";
		const boxButton = document.createElement('button');
		boxButton.innerHTML = "Box";
		const updateModeButtons = () => {
			brushButton.style.fontWeight = drawMode === 'brush' ? 'bold' : 'normal';
			boxButton.style.fontWeight = drawMode === 'box' ? 'bold' : 'normal';
			if(drawMode === 'box'){
				circleCursor.hidden = true;
				body.style.cursor = 'auto';
			}
		};
		brushButton.onclick = () => { drawMode = 'brush'; updateModeButtons(); };
		boxButton.onclick = () => { drawMode = 'box'; updateModeButtons(); };
		toolBoard.appendChild(brushButton);
		toolBoard.appendChild(boxButton);

		const invertButton = document.createElement('button');
		invertButton.innerHTML = "Invert";
		invertButton.onclick = () => {
			maskHistory.push(maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height));
			maskFuture = [];
			const imageData = maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height);
			const data = imageData.data;
			for(let i = 0; i < data.length; i += 4){
				if(data[i+3] > 0){
					data[i] = data[i+1] = data[i+2] = data[i+3] = 0;
				} else {
					data[i] = 255; data[i+1] = 255; data[i+2] = 0; data[i+3] = 255;
				}
			}
			maskingCtx.putImageData(imageData, 0, 0);
		};
		toolBoard.appendChild(invertButton);

		const clearButton = document.createElement('button');
		clearButton.innerHTML = "Clear";
		clearButton.onclick = () => {
			maskHistory.push(maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height));
			maskFuture = [];
			maskingCtx.clearRect(0, 0, maskingCanvas.width, maskingCanvas.height);
		};
		toolBoard.appendChild(clearButton);

		const maskButton = document.createElement('button');
		maskButton.innerHTML = "Mask";
		maskButton.addEventListener('mousedown', (e) => {
			maskingCanvas.hidden = true;
			ctx.putImageData(getMaskImageData(), 0, 0);
		});
		maskButton.addEventListener('mouseup', (e) => {
			maskingCanvas.hidden = false;
			ctx.putImageData(originalImageData, 0, 0);
		});
		toolBoard.appendChild(maskButton);

		const cropBoxButton = document.createElement('button');
		cropBoxButton.innerHTML = "Crop";
		cropBoxButton.onclick = () => {
			this.dispatchEvent(new CustomEvent('cropbox', { bubbles: true, composed: true }));
		};
		toolBoard.appendChild(cropBoxButton);

		const eraseButton = document.createElement('button');
		eraseButton.innerHTML = "Erase";
		eraseButton.onclick = () => {
			this.dispatchEvent(new CustomEvent('erase', { bubbles: true, composed: true }));
		};
		toolBoard.appendChild(eraseButton);

		const dlMaskButton = document.createElement('button');
		dlMaskButton.innerHTML = "\u2b07 Mask";
		dlMaskButton.onclick = () => {
			this.dispatchEvent(new CustomEvent('downloadmask', { bubbles: true, composed: true }));
		};
		toolBoard.appendChild(dlMaskButton);

		body.appendChild(toolBoard);
		}


		/*
		 * Getters & Setters
		 */

		this.maskImageDataBlob = () => {
			return imageDataBlob(getMaskImageData());
		};
		this.maskAlphaImageDataBlob = () => {
			return imageDataBlob(maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height));
		};
		this.maskAlphaImageDataValue = () => {
			return maskingCtx.getImageData(0, 0, maskingCanvas.width, maskingCanvas.height);
		};
	}
}

customElements.define('image-masker', Masker);

